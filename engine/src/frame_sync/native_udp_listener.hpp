// 2026-09-15: one owner for scoped UDP bootstrap, routing and retransmission.
// Private candidate: legacy FNAT ingress and native product integration remain separate tasks.
#pragma once
#include "frame_sync/native_udp_bootstrap.hpp"
#include "frame_sync/native_udp_stream.hpp"

namespace frame_sync {
struct NativeUDPListenerLimits {
  size_t connections=128;
  uint64_t cookie_lifetime_ms=30000,unaccepted_timeout_ms=5000;
  NativeUDPStreamLimits stream{};
  NativeUDPListenerLimits()=default;~NativeUDPListenerLimits()=default;
  NativeUDPListenerLimits(const NativeUDPListenerLimits&)=default;
  NativeUDPListenerLimits& operator=(const NativeUDPListenerLimits&)=default;
  NativeUDPListenerLimits(NativeUDPListenerLimits&&)=default;
  NativeUDPListenerLimits& operator=(NativeUDPListenerLimits&&)=default;
  void Validate() const {
    stream.Validate();
    if(!connections || connections>NativeUDPConnectionRegistry::kCapacity ||
       !cookie_lifetime_ms || cookie_lifetime_ms>30000 ||
       !unaccepted_timeout_ms || unaccepted_timeout_ms>30000 ||
       stream.datagrams.byte_limit<=kReliableUDP_SessionHeaderSize)
      throw std::invalid_argument("Invalid native UDP listener limits");
  }
};
struct NativeUDPListenerStats {
  bool open=false,accept_pending=false;
  size_t active=0,retired=0,unaccepted=0;
  size_t pending_bytes=0,receive_capacity=0,reorder_bytes=0;
  uint64_t challenges=0,accepted=0,duplicates=0,rejected=0,ignored=0,reply_errors=0;
  NativeUDPListenerStats()=default;~NativeUDPListenerStats()=default;
  NativeUDPListenerStats(const NativeUDPListenerStats&)=default;
  NativeUDPListenerStats& operator=(const NativeUDPListenerStats&)=default;
  NativeUDPListenerStats(NativeUDPListenerStats&&)=default;
  NativeUDPListenerStats& operator=(NativeUDPListenerStats&&)=default;
};
class NativeUDPAcceptor {
 public:
  using executor_type=NativeUDPSocket::executor_type;
  using Error=boost::system::error_code;
  using Clock=ReliableUDPChannel::Clock;
  using NowFn=ReliableUDPChannel::NowFn;
 private:
  using Completion=std::move_only_function<void(Error,NativeUDPSocket)>;
  struct Entry {
    NativeUDPAddress address{};
    ReliableUDPConnection connection{};
    NativeUDPSocket::Control control{};
    std::optional<NativeUDPSocket> unaccepted;
    uint64_t admitted=0;
    bool occupied=false;
    Entry()=default;~Entry()=default;
    Entry(const Entry&)=delete;Entry& operator=(const Entry&)=delete;
    Entry(Entry&&)=default;Entry& operator=(Entry&&)=default;
  };
  struct State : std::enable_shared_from_this<State> {
    State(asio::io_context& io,const udp::endpoint& endpoint,NativeUDPListenerLimits limits,
          NowFn now,NativeRecoveryCredentials::Entropy entropy)
      :executor(asio::make_strand(io)),limits(std::move(limits)),now(std::move(now)),
       signer(this->limits.cookie_lifetime_ms,std::move(entropy)),registry(this->limits.connections),
       wire(std::make_shared<udp::socket>(executor,endpoint)),bound(wire->local_endpoint()),timer(executor) {
      wire->non_blocking(true);
    }
    State()=delete;~State()=default;
    State(const State&)=delete;State& operator=(const State&)=delete;
    State(State&&)=delete;State& operator=(State&&)=delete;
    uint64_t Milliseconds() const {
      const auto value=std::chrono::duration_cast<std::chrono::milliseconds>(now().time_since_epoch()).count();
      if(value<0)throw std::logic_error("Negative native UDP listener clock");
      return static_cast<uint64_t>(value);
    }
    void Start() {
      asio::post(executor,[self=this->shared_from_this()] {
        std::lock_guard lock(self->mutex);
        if(!self->closed){self->ReceiveLocked();self->TimerLocked();}
      });
    }
    // Stream operations may complete on another executor. Completion only posts;
    // it never invokes a session or application callback under this mutex.
    void Accept(Completion completion) {
      std::lock_guard lock(mutex);
      if(closed){completion(asio::error::operation_aborted,NativeUDPSocket(executor));return;}
      if(accept_done){completion(asio::error::already_started,NativeUDPSocket(executor));return;}
      accept_done=std::move(completion);CompleteAcceptLocked();
    }
    void CompleteAcceptLocked() {
      if(!accept_done)return;
      for(auto& entry:entries) {
        if(!entry.unaccepted)continue;
        auto stats=entry.control.Stats();
        if(!stats || !stats->open)continue;
        auto stream=std::move(*entry.unaccepted);entry.unaccepted.reset();
        auto done=std::move(accept_done);++counters.accepted;
        done({},std::move(stream));return;
      }
    }
    void StopWire() {
      Error ignored;wire->close(ignored);timer.cancel();
    }
    void CloseLocked(Error reason) {
      if(closed)return;closed=true;
      for(auto& entry:entries) {
        entry.control.Close();entry.unaccepted.reset();entry.occupied=false;
      }
      if(accept_done) {
        auto done=std::move(accept_done);done(reason,NativeUDPSocket(executor));
      }
      // Actual shared-socket close is always serialized with receive/send/tick.
      asio::post(executor,[self=this->shared_from_this()]{self->StopWire();});
    }
    void Close() {
      std::lock_guard lock(mutex);CloseLocked(asio::error::operation_aborted);
    }
    void RetireLocked(size_t index,uint64_t current) {
      auto& entry=entries[index];
      if(!entry.occupied)return;
      entry.control.Close();entry.unaccepted.reset();
      registry.retire(entry.address,entry.connection,current);
      entry.control={};entry.occupied=false;
    }
    bool SweepLocked(uint64_t current,bool retransmit) {
      if(!registry.maintain(current)) {
        CloseLocked(asio::error::invalid_argument);return false;
      }
      for(size_t i=0;i<limits.connections;++i) {
        auto& entry=entries[i];if(!entry.occupied)continue;
        auto stats=entry.control.Stats();
        if(!stats || !stats->open ||
           (entry.unaccepted && current-entry.admitted>=limits.unaccepted_timeout_ms)) {
          RetireLocked(i,current);continue;
        }
        if(retransmit && !entry.control.Tick())RetireLocked(i,current);
      }
      return !closed;
    }
    void ReplyLocked(const udp::endpoint& peer,const NativeUDPBootstrapPacket& packet) {
      Error error;const auto sent=wire->send_to(asio::buffer(packet),peer,0,error);
      // A dropped challenge/welcome is retried by the bounded client attempt.
      // No per-peer or global pending-reply queue grows under a Hello flood.
      if(error || sent!=packet.size())++counters.reply_errors;
    }
    void PacketLocked(const udp::endpoint& peer,std::span<const uint8_t> bytes) {
      const auto key=native_udp_bootstrap::address(peer);
      if(!key){++counters.ignored;return;}
      const auto current=Milliseconds();
      if(auto bootstrap=native_udp_bootstrap::decode(bytes)) {
        if(bootstrap->kind==NativeUDPBootstrapKind::Hello) {
          if(auto packet=signer.challenge(bytes,*key,current)) {
            ++counters.challenges;ReplyLocked(peer,*packet);
          }
          return;
        }
        if(bootstrap->kind!=NativeUDPBootstrapKind::Confirm){++counters.ignored;return;}
        auto lease=signer.verify(bytes,*key,current);
        if(!lease){++counters.rejected;return;}
        // 2026-09-15 preflight: original PacketLocked swept all 128 streams for
        // every datagram. Sweep only admission and the periodic timer; scoped
        // data routes directly to its one generation.
        if(!SweepLocked(current,false))return;
        auto claim=registry.claim(*lease,current);
        if(!claim){++counters.rejected;return;}
        const auto [index,fresh]=*claim;
        auto& entry=entries[index];
        if(fresh) {
          try {
            entry.unaccepted.emplace(wire,peer,executor,lease->connection(),limits.stream,now);
          } catch(const std::exception&) {
            registry.retire(*key,lease->connection(),current);++counters.rejected;return;
          }
          entry.address=*key;entry.connection=lease->connection();entry.control=entry.unaccepted->control();
          entry.admitted=current;entry.occupied=true;
        } else {
          // Registry proof alone cannot revive a destroyed/closed stream.
          auto stats=entry.control.Stats();
          if(!entry.occupied || !stats || !stats->open) {
            RetireLocked(index,current);++counters.rejected;return;
          }
          ++counters.duplicates;
        }
        ReplyLocked(peer,lease->reply());CompleteAcceptLocked();return;
      }
      if(bytes.size()>=kReliableUDP_SessionAckSize &&
         (bytes[0]==kReliableUDP_SessionData || bytes[0]==kReliableUDP_SessionAck)) {
        ReliableUDPConnection id{};std::copy_n(bytes.begin()+1,id.size(),id.begin());
        auto index=registry.find(*key,id);
        if(index) {
          auto& entry=entries[*index];
          if(!entry.control.Deliver(peer,bytes))RetireLocked(*index,current);
          return;
        }
      }
      ++counters.ignored;
    }
    void ReceiveLocked() {
      wire->async_receive_from(asio::buffer(receive),source,
        [self=this->shared_from_this()](Error error,size_t bytes) {
          std::lock_guard lock(self->mutex);
          if(self->closed)return;
          if(error) {
            if(error!=asio::error::message_size) {self->CloseLocked(error);return;}
            ++self->counters.ignored;
          } else {
            try {self->PacketLocked(self->source,std::span(self->receive.data(),bytes));}
            catch(const std::exception&) {self->CloseLocked(asio::error::fault);}
          }
          if(!self->closed)self->ReceiveLocked();
        });
    }
    void TimerLocked() {
      timer.expires_after(std::chrono::milliseconds(25));
      timer.async_wait([self=this->shared_from_this()](Error error) {
        std::lock_guard lock(self->mutex);
        if(error || self->closed)return;
        try {
          if(self->SweepLocked(self->Milliseconds(),true))self->TimerLocked();
        } catch(const std::exception&) {self->CloseLocked(asio::error::fault);}
      });
    }
    NativeUDPListenerStats Stats() const {
      std::lock_guard lock(mutex);auto result=counters;
      result.open=!closed;result.accept_pending=bool(accept_done);
      if(closed)return result;
      result.active=registry.active();result.retired=registry.retired();
      for(const auto& entry:entries) {
        result.unaccepted+=entry.unaccepted.has_value();
        if(auto stats=entry.control.Stats()) {
          result.pending_bytes+=stats->pending_bytes;
          result.receive_capacity+=stats->receive_capacity;
          result.reorder_bytes+=stats->reorder_bytes;
        }
      }
      return result;
    }
    const executor_type executor;
    const NativeUDPListenerLimits limits;
    const NowFn now;
    NativeUDPBootstrapSigner signer;
    NativeUDPConnectionRegistry registry;
    const std::shared_ptr<udp::socket> wire;
    const udp::endpoint bound;
    asio::steady_timer timer;
    mutable std::mutex mutex;
    std::array<Entry,NativeUDPConnectionRegistry::kCapacity> entries{};
    std::array<uint8_t,kReliableUDP_MaxPacketSize+1> receive{};
    udp::endpoint source;
    Completion accept_done;
    NativeUDPListenerStats counters{};
    bool closed=false;
  };
  template<class Handler>
  static Completion OnAssociatedExecutor(Handler&& handler,const executor_type& owner) {
    auto target=asio::get_associated_executor(handler,owner);
    // 2026-09-15 preflight: associated and owner executors may have different work-guard types.
    // auto target_work=asio::make_work_guard(target),owner_work=asio::make_work_guard(owner);
    // 2026-09-15: auto target_work=asio::make_work_guard(target);
    auto target_work=KeepNativeUDPExecutorAlive(target);
    // 2026-09-15: auto owner_work=asio::make_work_guard(owner);
    auto owner_work=KeepNativeUDPExecutorAlive(owner);
    return [handler=std::forward<Handler>(handler),target,target_work=std::move(target_work),
            owner_work=std::move(owner_work)](Error error,NativeUDPSocket socket) mutable {
      asio::post(target,[handler=std::move(handler),target_work=std::move(target_work),
                        owner_work=std::move(owner_work),error,socket=std::move(socket)]() mutable {
        std::move(handler)(error,std::move(socket));
      });
    };
  }
 public:
  NativeUDPAcceptor()=delete;
  NativeUDPAcceptor(asio::io_context& io,const udp::endpoint& endpoint,NativeUDPListenerLimits limits={},
      NowFn now=Clock::now,NativeRecoveryCredentials::Entropy entropy=native_entropy) {
    limits.Validate();
    if(!now || !entropy)throw std::invalid_argument("Native UDP listener requires clock and entropy");
    state_=std::make_shared<State>(io,endpoint,std::move(limits),std::move(now),std::move(entropy));
    state_->Start();
  }
  ~NativeUDPAcceptor(){state_->Close();}
  NativeUDPAcceptor(const NativeUDPAcceptor&)=delete;NativeUDPAcceptor& operator=(const NativeUDPAcceptor&)=delete;
  NativeUDPAcceptor(NativeUDPAcceptor&&)=delete;NativeUDPAcceptor& operator=(NativeUDPAcceptor&&)=delete;
  executor_type get_executor() const noexcept {return state_->executor;}
  udp::endpoint local_endpoint() const {return state_->bound;}
  bool is_open() const {return state_->Stats().open;}
  void close(Error& error){error.clear();state_->Close();}
  void close(){state_->Close();}
  NativeUDPListenerStats stats() const {return state_->Stats();}
  template<class CompletionToken> auto async_accept(CompletionToken&& token) {
    return asio::async_initiate<CompletionToken,void(Error,NativeUDPSocket)>(
      [state=state_](auto&& handler) {
        state->Accept(OnAssociatedExecutor(std::forward<decltype(handler)>(handler),state->executor));
      },token);
  }
 private:
  // 2026-09-15: retain the listener state that every public operation owns.
  std::shared_ptr<State> state_;
};
struct NativeUDPTransport {
  using Socket=NativeUDPSocket;using Acceptor=NativeUDPAcceptor;
  NativeUDPTransport()=delete;~NativeUDPTransport()=default;
  NativeUDPTransport(const NativeUDPTransport&)=delete;NativeUDPTransport& operator=(const NativeUDPTransport&)=delete;
  NativeUDPTransport(NativeUDPTransport&&)=delete;NativeUDPTransport& operator=(NativeUDPTransport&&)=delete;
  static udp::endpoint BindEndpoint(unsigned short port){return {udp::v4(),port};}
  // 2026-09-21: application enqueue completion does not acknowledge a UDP datagram.
  // State::Close synchronously detaches retained accept/read handlers, while
  // physical socket close remains on the listener strand.
  static void BeginClose(Acceptor& acceptor) { acceptor.close(); }
  static bool OutputDrained(const Socket& socket) {
    const auto state=socket.control().Stats();
    return !state || !state->open || (!state->writing && state->pending_packets==0);
  }
  static void Configure(Socket& socket,bool,int,boost::system::error_code& error) {
    error=socket.is_open() ? boost::system::error_code{} : asio::error::bad_descriptor;
  }
};
} // namespace frame_sync
