// 2026-09-15: bounded client-side UDP connection establishment and IO ownership.
// FNRC credentials, loading, input and replay remain in the shared native client.
#pragma once
#include "frame_sync/native_udp_stream.hpp"
#include "frame_sync/native_udp_bootstrap.hpp"
#include <atomic>
namespace frame_sync {
struct NativeUDPDialLimits {
  uint64_t timeout_ms=5000;
  NativeUDPStreamLimits stream{};
  NativeUDPDialLimits()=default;~NativeUDPDialLimits()=default;
  NativeUDPDialLimits(const NativeUDPDialLimits&)=default;
  NativeUDPDialLimits& operator=(const NativeUDPDialLimits&)=default;
  NativeUDPDialLimits(NativeUDPDialLimits&&)=default;
  NativeUDPDialLimits& operator=(NativeUDPDialLimits&&)=default;
  void Validate() const {
    stream.Validate();
    if(!timeout_ms || timeout_ms>30000 || stream.datagrams.byte_limit<=kReliableUDP_SessionHeaderSize)
      throw std::invalid_argument("Invalid native UDP dial deadline or stream budget");
  }
};
struct NativeUDPEndpoints {
  static constexpr size_t kCapacity=8;
  std::array<udp::endpoint,kCapacity> values{};
  size_t count=0;
  NativeUDPEndpoints()=default;~NativeUDPEndpoints()=default;
  NativeUDPEndpoints(const NativeUDPEndpoints&)=default;
  NativeUDPEndpoints& operator=(const NativeUDPEndpoints&)=default;
  NativeUDPEndpoints(NativeUDPEndpoints&&)=default;
  NativeUDPEndpoints& operator=(NativeUDPEndpoints&&)=default;
  explicit NativeUDPEndpoints(std::span<const udp::endpoint> endpoints) {
    if(endpoints.empty() || endpoints.size()>kCapacity)
      throw std::invalid_argument("Native UDP dial requires one to eight resolved endpoints");
    for(const auto& endpoint:endpoints) {
      if(!native_udp_bootstrap::address(endpoint))throw std::invalid_argument("Invalid native UDP dial peer");
      Add(endpoint);
    }
  }
  void Add(const udp::endpoint& endpoint) {
    // 2026-09-15 preflight: public value types may be modified by their caller.
    // if(count==values.size() || !native_udp_bootstrap::address(endpoint))return;
    if(count>=values.size() || !native_udp_bootstrap::address(endpoint))return;
    for(size_t i=0;i<count;++i)if(values[i]==endpoint)return;
    values[count++]=endpoint;
  }
};
struct NativeUDPDialStats {
  bool busy=false,connected=false,cancel_requested=false;
  size_t resolved_endpoints=0,physical_attempts=0,handshake_packets=0,ignored_packets=0;
  uint64_t deadline_ms=0;
  std::optional<udp::endpoint> local,remote;
  std::optional<NativeUDPStreamStats> stream;
  NativeUDPDialStats()=default;~NativeUDPDialStats()=default;
  NativeUDPDialStats(const NativeUDPDialStats&)=default;
  NativeUDPDialStats& operator=(const NativeUDPDialStats&)=default;
  NativeUDPDialStats(NativeUDPDialStats&&)=default;
  NativeUDPDialStats& operator=(NativeUDPDialStats&&)=default;
};
class NativeUDPDialer {
 public:
  using executor_type=NativeUDPSocket::executor_type;
  using Error=boost::system::error_code;
  using Clock=ReliableUDPChannel::Clock;
  using NowFn=ReliableUDPChannel::NowFn;
 private:
  using Completion=std::move_only_function<void(Error,NativeUDPSocket)>;
  struct Physical {
    Physical(executor_type executor,udp::endpoint endpoint,uint64_t current,uint64_t allowance,
             NativeRecoveryCredentials::Entropy entropy)
      :wire(std::make_shared<udp::socket>(executor,udp::endpoint(endpoint.protocol(),0))),
       remote(std::move(endpoint)),bootstrap(*native_udp_bootstrap::address(remote),current,allowance,entropy),
       until(current+allowance) {
      wire->non_blocking(true);local=wire->local_endpoint();
    }
    Physical()=delete;~Physical()=default;
    Physical(const Physical&)=delete;Physical& operator=(const Physical&)=delete;
    Physical(Physical&&)=delete;Physical& operator=(Physical&&)=delete;
    void Close() {control.Close();Error ignored;wire->close(ignored);}
    const std::shared_ptr<udp::socket> wire;
    const udp::endpoint remote;
    udp::endpoint local,source;
    NativeUDPBootstrapAttempt bootstrap;
    const uint64_t until;
    uint64_t next_send=0;
    NativeUDPSocket::Control control;
    std::array<uint8_t,kReliableUDP_MaxPacketSize+1> receive{};
  };
  struct State : std::enable_shared_from_this<State> {
    State(executor_type executor,NativeUDPDialLimits limits,NowFn now,
          NativeRecoveryCredentials::Entropy entropy,Completion completion,
          std::string host,unsigned short port,NativeUDPEndpoints endpoints)
      :executor(std::move(executor)),limits(std::move(limits)),now(std::move(now)),entropy(entropy),
       resolver(this->executor),timer(this->executor),done(std::move(completion)),
       host(std::move(host)),port(port),endpoints(std::move(endpoints)) {
      const auto current=Milliseconds();
      if(current>std::numeric_limits<uint64_t>::max()-this->limits.timeout_ms)
        throw std::invalid_argument("Native UDP dial deadline overflow");
      deadline=current+this->limits.timeout_ms;
    }
    State()=delete;~State()=default;
    State(const State&)=delete;State& operator=(const State&)=delete;
    State(State&&)=delete;State& operator=(State&&)=delete;
    uint64_t Milliseconds() const {
      const auto value=std::chrono::duration_cast<std::chrono::milliseconds>(now().time_since_epoch()).count();
      if(value<0)throw std::logic_error("Negative native UDP dial clock");
      return static_cast<uint64_t>(value);
    }
    void StopLocked(Error error) {
      if(closed)return;closed=true;connected=false;
      resolver.cancel();timer.cancel();
      if(physical){physical->Close();physical.reset();}
      if(done){auto completion=std::move(done);completion(error,NativeUDPSocket(executor));}
    }
    bool CurrentLocked(const std::shared_ptr<Physical>& attempt) {
      if(closed)return false;
      if(cancelled.load()){StopLocked(asio::error::operation_aborted);return false;}
      return physical==attempt;
    }
    bool TimeLocked(uint64_t current) {
      if(current<last_time){StopLocked(asio::error::invalid_argument);return false;}
      last_time=current;
      if(cancelled.load()){StopLocked(asio::error::operation_aborted);return false;}
      if(!connected && current>=deadline){StopLocked(asio::error::timed_out);return false;}
      return !closed;
    }
    void Cancel() {
      // 2026-09-15 preflight: repeated Cancel must not enqueue repeated shutdown work.
      // cancelled.store(true);
      if(cancelled.exchange(true))return;
      asio::post(executor,[self=this->shared_from_this()] {
        std::lock_guard lock(self->mutex);self->StopLocked(asio::error::operation_aborted);
      });
    }
    void Start() {
      asio::post(executor,[self=this->shared_from_this()] {
        std::lock_guard lock(self->mutex);
        try {self->StartLocked();}catch(const std::exception&){self->StopLocked(asio::error::fault);}
      });
    }
    void StartLocked() {
      const auto current=Milliseconds();if(!TimeLocked(current))return;
      TimerLocked();
      if(endpoints.count){NextLocked(current);return;}
      // Numeric addresses do not start a resolver worker.
      Error parsed;auto address=asio::ip::make_address(host,parsed);
      if(!parsed) {endpoints.Add(udp::endpoint(address,port));NextLocked(current);return;}
      resolver.async_resolve(host,std::to_string(port),udp::resolver::numeric_service,
        [self=this->shared_from_this()](Error error,udp::resolver::results_type results) {
          std::lock_guard lock(self->mutex);if(self->closed)return;
          try {
            const auto current=self->Milliseconds();if(!self->TimeLocked(current))return;
            if(error){self->StopLocked(error);return;}
            for(const auto& result:results) {
              self->endpoints.Add(result.endpoint());
              if(self->endpoints.count==NativeUDPEndpoints::kCapacity)break;
            }
            self->NextLocked(current);
          }catch(const std::exception&){self->StopLocked(asio::error::fault);}
        });
    }
    void NextLocked(uint64_t current) {
      if(!TimeLocked(current))return;
      if(physical){physical->Close();physical.reset();}
      Error last_error=asio::error::host_unreachable;
      while(next_endpoint<endpoints.count) {
        const auto remaining=endpoints.count-next_endpoint;
        const auto available=deadline-current;
        const uint64_t allowance=remaining==1 ? available :
          std::min(available,std::clamp<uint64_t>(available/remaining,250,1500));
        const auto remote=endpoints.values[next_endpoint++];++physical_attempts;
        try {physical=std::make_shared<Physical>(executor,remote,current,allowance,entropy);}
        catch(const boost::system::system_error& error){last_error=error.code();continue;}
        // Separate Physical storage survives cancelled old receive callbacks.
        ReceiveLocked(physical);SendLocked(physical,current);return;
      }
      StopLocked(last_error);
    }
    void SendLocked(const std::shared_ptr<Physical>& attempt,uint64_t current) {
      if(!CurrentLocked(attempt) || connected)return;
      auto packet=attempt->bootstrap.next_packet(current);
      if(!packet){NextLocked(current);return;}
      Error error;
      const auto sent=attempt->wire->send_to(asio::buffer(*packet),attempt->remote,0,error);
      ++handshake_packets;attempt->next_send=current+100;
      if(error && error!=asio::error::would_block && error!=asio::error::try_again) {
        NextLocked(current);return;
      }
      (void)sent; // A short/dropped datagram is retried within the unchanged deadline.
    }
    void PacketLocked(const std::shared_ptr<Physical>& attempt,size_t bytes) {
      if(!CurrentLocked(attempt))return;
      if(attempt->source!=attempt->remote){++ignored_packets;return;}
      const auto current=Milliseconds();if(!TimeLocked(current))return;
      const auto packet=std::span<const uint8_t>(attempt->receive.data(),bytes);
      if(connected) {
        if(!attempt->control.Deliver(attempt->source,packet))StopLocked(asio::error::network_reset);
        return;
      }
      if(current>=attempt->until){NextLocked(current);return;}
      const auto before=attempt->bootstrap.state();
      if(attempt->bootstrap.receive(packet,*native_udp_bootstrap::address(attempt->source),current)) {
        NativeUDPSocket socket(attempt->wire,attempt->remote,executor,attempt->bootstrap.connection(),limits.stream,now);
        attempt->control=socket.control();connected=true;
        auto completion=std::move(done);completion({},std::move(socket));return;
      }
      if(before!=attempt->bootstrap.state())SendLocked(attempt,current);
      else ++ignored_packets;
    }
    void ReceiveLocked(const std::shared_ptr<Physical>& attempt) {
      attempt->wire->async_receive_from(asio::buffer(attempt->receive),attempt->source,
        [self=this->shared_from_this(),attempt](Error error,size_t bytes) {
          std::lock_guard lock(self->mutex);
          if(!self->CurrentLocked(attempt))return;
          try {
            if(error) {
              if(error==asio::error::message_size)++self->ignored_packets;
              else if(self->connected){self->StopLocked(error);return;}
              else {self->NextLocked(self->Milliseconds());return;}
            } else self->PacketLocked(attempt,bytes);
            if(self->CurrentLocked(attempt))self->ReceiveLocked(attempt);
          }catch(const std::exception&){self->StopLocked(asio::error::fault);}
        });
    }
    void TimerLocked() {
      timer.expires_after(std::chrono::milliseconds(25));
      timer.async_wait([self=this->shared_from_this()](Error error) {
        std::lock_guard lock(self->mutex);if(error || self->closed)return;
        try {
          const auto current=self->Milliseconds();if(!self->TimeLocked(current))return;
          if(self->physical) {
            if(self->connected) {
              auto stats=self->physical->control.Stats();
              if(!stats || !stats->open || !self->physical->control.Tick()) {
                self->StopLocked(asio::error::operation_aborted);return;
              }
            } else if(current>=self->physical->until)self->NextLocked(current);
            else if(current>=self->physical->next_send)self->SendLocked(self->physical,current);
          }
          if(!self->closed)self->TimerLocked();
        }catch(const std::exception&){self->StopLocked(asio::error::fault);}
      });
    }
    NativeUDPDialStats Stats() const {
      std::lock_guard lock(mutex);NativeUDPDialStats result;
      result.busy=!closed;result.connected=connected;result.cancel_requested=cancelled.load();
      result.resolved_endpoints=endpoints.count;result.physical_attempts=physical_attempts;
      result.handshake_packets=handshake_packets;result.ignored_packets=ignored_packets;
      result.deadline_ms=deadline;
      if(physical){result.local=physical->local;result.remote=physical->remote;result.stream=physical->control.Stats();}
      return result;
    }
    const executor_type executor;
    const NativeUDPDialLimits limits;
    const NowFn now;
    const NativeRecoveryCredentials::Entropy entropy;
    udp::resolver resolver;
    asio::steady_timer timer;
    mutable std::mutex mutex;
    std::atomic<bool> cancelled{false};
    Completion done;
    const std::string host;
    const unsigned short port;
    NativeUDPEndpoints endpoints;
    size_t next_endpoint=0,physical_attempts=0,handshake_packets=0,ignored_packets=0;
    uint64_t deadline=0,last_time=0;
    std::shared_ptr<Physical> physical;
    bool connected=false,closed=false;
  };
  template<class Handler>
  static Completion OnAssociatedExecutor(Handler&& handler,const executor_type& owner) {
    auto target=asio::get_associated_executor(handler,owner);
    // 2026-09-15: modern and legacy executor retention follows verified stream D.
    // auto target_work=asio::make_work_guard(target);
    auto target_work=KeepNativeUDPExecutorAlive(target);
    // 2026-09-15: modern and legacy executor retention follows verified stream D.
    // auto owner_work=asio::make_work_guard(owner);
    auto owner_work=KeepNativeUDPExecutorAlive(owner);
    return [handler=std::forward<Handler>(handler),target,target_work=std::move(target_work),
            owner_work=std::move(owner_work)](Error error,NativeUDPSocket socket) mutable {
      asio::post(target,[handler=std::move(handler),target_work=std::move(target_work),
                        owner_work=std::move(owner_work),error,socket=std::move(socket)]() mutable {
        std::move(handler)(error,std::move(socket));
      });
    };
  }
  void Submit(std::string host,unsigned short port,NativeUDPEndpoints endpoints,Completion done) {
    if(endpoints.count) {
      if(endpoints.count>endpoints.values.size())throw std::invalid_argument("Invalid native UDP endpoint count");
      for(size_t i=0;i<endpoints.count;++i)
        if(!native_udp_bootstrap::address(endpoints.values[i]))throw std::invalid_argument("Invalid native UDP endpoint");
    // 2026-09-15 preflight: a NUL would let the OS resolver silently truncate the requested host.
    // } else if(host.empty() || host.size()>255 || !port)throw std::invalid_argument("Invalid native UDP host or service");
    } else if(host.empty() || host.size()>255 || host.find(char{})!=std::string::npos || !port)
      throw std::invalid_argument("Invalid native UDP host or service");
    std::lock_guard lock(mutex_);
    if(state_ && state_->Stats().busy) {
      done(asio::error::already_started,NativeUDPSocket(executor_));return;
    }
    auto state=std::make_shared<State>(executor_,limits_,now_,entropy_,std::move(done),
                                       std::move(host),port,std::move(endpoints));
    state_=state;state->Start();
  }
 public:
  NativeUDPDialer()=delete;
  explicit NativeUDPDialer(asio::io_context& io,NativeUDPDialLimits limits={},
      NowFn now=Clock::now,NativeRecoveryCredentials::Entropy entropy=native_entropy)
    :executor_(asio::make_strand(io)),limits_(std::move(limits)),now_(std::move(now)),entropy_(entropy) {
    limits_.Validate();
    if(!now_ || !entropy_)throw std::invalid_argument("Native UDP dial requires clock and entropy");
  }
  ~NativeUDPDialer(){Cancel();}
  NativeUDPDialer(const NativeUDPDialer&)=delete;NativeUDPDialer& operator=(const NativeUDPDialer&)=delete;
  NativeUDPDialer(NativeUDPDialer&&)=delete;NativeUDPDialer& operator=(NativeUDPDialer&&)=delete;
  executor_type get_executor() const noexcept {return executor_;}
  void Cancel() {
    std::shared_ptr<State> state;
    {std::lock_guard lock(mutex_);state=state_;}
    if(state)state->Cancel();
  }
  NativeUDPDialStats stats() const {
    std::lock_guard lock(mutex_);
    return state_ ? state_->Stats() : NativeUDPDialStats{};
  }
  template<class CompletionToken>
  auto async_connect(std::string host,unsigned short port,CompletionToken&& token) {
    return asio::async_initiate<CompletionToken,void(Error,NativeUDPSocket)>(
      [this,host=std::move(host),port](auto&& handler) mutable {
        Submit(std::move(host),port,{},OnAssociatedExecutor(std::forward<decltype(handler)>(handler),executor_));
      },token);
  }
  template<class CompletionToken>
  auto async_connect(NativeUDPEndpoints endpoints,CompletionToken&& token) {
    return asio::async_initiate<CompletionToken,void(Error,NativeUDPSocket)>(
      [this,endpoints=std::move(endpoints)](auto&& handler) mutable {
        if(!endpoints.count)throw std::invalid_argument("Native UDP resolved endpoint list is empty");
        Submit({},0,std::move(endpoints),OnAssociatedExecutor(std::forward<decltype(handler)>(handler),executor_));
      },token);
  }
 private:
  const executor_type executor_;
  const NativeUDPDialLimits limits_;
  const NowFn now_;
  const NativeRecoveryCredentials::Entropy entropy_;
  mutable std::mutex mutex_;
  std::shared_ptr<State> state_;
};
} // namespace frame_sync
