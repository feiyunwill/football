// 2026-09-15: bounded asynchronous byte stream over one reliable UDP generation.
// The listener owns the shared datagram socket and serializes all actual IO.
// A stream close only releases its own channel, buffered bytes and operations.
#pragma once
#include "frame_sync/reliable_udp.hpp"
#include <boost/asio/associated_executor.hpp>
#include <boost/asio/executor_work_guard.hpp>
#include <span>
#include <memory>

namespace frame_sync {
// 2026-09-15: strand<any_io_executor> advertises legacy executor traits, but its
// inner any_io_executor has no on_work_started/on_work_finished. Use tracked
// execution properties for modern executors and the legacy guard only where required.
template<class Executor> auto KeepNativeUDPExecutorAlive(const Executor& executor) {
  if constexpr(asio::execution::is_executor<Executor>::value)
    return asio::prefer(executor,asio::execution::outstanding_work.tracked);
  else return asio::make_work_guard(executor);
}
struct NativeUDPStreamLimits {
  DatagramBudget datagrams{64,64*1200};
  // 2026-09-15: original 64 KiB could overflow on one reordered 64-packet window.
  // size_t receive_bytes=64*1024;
  size_t receive_bytes=128*1024;
  NativeUDPStreamLimits()=default;
  NativeUDPStreamLimits(DatagramBudget budget,size_t bytes):datagrams(budget),receive_bytes(bytes){Validate();}
  ~NativeUDPStreamLimits()=default;
  NativeUDPStreamLimits(const NativeUDPStreamLimits&)=default;
  NativeUDPStreamLimits& operator=(const NativeUDPStreamLimits&)=default;
  NativeUDPStreamLimits(NativeUDPStreamLimits&&)=default;
  NativeUDPStreamLimits& operator=(NativeUDPStreamLimits&&)=default;
  void Validate() const {
    DatagramBudget checked(datagrams.packet_limit,datagrams.byte_limit);
    if(!receive_bytes || receive_bytes>1024*1024)
      throw std::invalid_argument("Invalid native UDP stream receive capacity");
  }
};
struct NativeUDPStreamStats {
  bool open=false,reading=false,writing=false;
  size_t pending_packets=0,pending_bytes=0,reorder_bytes=0;
  size_t receive_bytes=0,receive_capacity=0;
  NativeUDPStreamStats()=default;~NativeUDPStreamStats()=default;
  NativeUDPStreamStats(const NativeUDPStreamStats&)=default;
  NativeUDPStreamStats& operator=(const NativeUDPStreamStats&)=default;
  NativeUDPStreamStats(NativeUDPStreamStats&&)=default;
  NativeUDPStreamStats& operator=(NativeUDPStreamStats&&)=default;
};
class NativeUDPSocket {
 public:
  using executor_type=asio::strand<asio::any_io_executor>;
  using Error=boost::system::error_code;
 private:
  using Completion=std::move_only_function<void(Error,size_t)>;
  struct State : std::enable_shared_from_this<State> {
    State(std::shared_ptr<udp::socket> socket,udp::endpoint remote,executor_type executor,
          const NativeUDPStreamLimits& limits,size_t write_limit)
      :socket(std::move(socket)),remote(std::move(remote)),executor(std::move(executor)),
       receive(limits.receive_bytes),write_limit(write_limit) {}
    State()=delete;~State()=default;
    State(const State&)=delete;State& operator=(const State&)=delete;
    State(State&&)=delete;State& operator=(State&&)=delete;

    void RequireOwner() const {
      if(!executor.running_in_this_thread())
        throw std::logic_error("Datagram delivery and retransmission require the listener executor");
    }
    Error ChannelError() const {
      switch(channel->status()) {
        case UDPChannelStatus::Capacity:return asio::error::no_buffer_space;
        case UDPChannelStatus::RetriesExhausted:return asio::error::timed_out;
        case UDPChannelStatus::InvalidPayload:return asio::error::invalid_argument;
        case UDPChannelStatus::Closed:return asio::error::operation_aborted;
        default:return asio::error::network_reset;
      }
    }
    void FailLocked(Error error) {
      if(closed)return;
      closed=true;
      channel->Close();
      std::vector<uint8_t>().swap(receive);head=used=0;
      if(read_done) {auto done=std::move(read_done);read_buffer={};done(error,0);}
      if(write_done) {auto done=std::move(write_done);write_size=0;done(error,0);}
    }
    void Close() {
      std::lock_guard lock(mutex);FailLocked(asio::error::operation_aborted);
    }
    void ReadLocked() {
      if(!read_done || !used)return;
      const size_t count=std::min(used,read_buffer.size());
      const size_t first=std::min(count,receive.size()-head);
      std::memcpy(read_buffer.data(),receive.data()+head,first);
      if(count>first)std::memcpy(static_cast<uint8_t*>(read_buffer.data())+first,receive.data(),count-first);
      head=(head+count)%receive.size();used-=count;
      auto done=std::move(read_done);read_buffer={};done({},count);
    }
    // Invoked synchronously by channel under this State's mutex, after the
    // reliable channel releases its own mutex. Completion handlers are posted.
    void DataLocked(const uint8_t* bytes,size_t count) {
      if(closed || !count)return;
      if(count>receive.size()-used){FailLocked(asio::error::no_buffer_space);return;}
      const size_t tail=(head+used)%receive.size();
      const size_t first=std::min(count,receive.size()-tail);
      std::memcpy(receive.data()+tail,bytes,first);
      if(count>first)std::memcpy(receive.data(),bytes+first,count-first);
      used+=count;ReadLocked();
    }
    void WriteLocked() {
      if(closed || !write_done)return;
      if(!channel->Send(write_bytes.data(),write_size)) {
        if(channel->status()!=UDPChannelStatus::Capacity)FailLocked(ChannelError());
        return;
      }
      const size_t count=write_size;write_size=0;
      auto done=std::move(write_done);done({},count);
    }
    template<class Buffers> void SubmitWrite(const Buffers& buffers,Completion done) {
      std::lock_guard lock(mutex);
      if(closed){done(asio::error::operation_aborted,0);return;}
      if(write_done){done(asio::error::already_started,0);return;}
      // Copy at most one datagram, even for a huge scatter/gather message.
      write_size=asio::buffer_copy(asio::buffer(write_bytes.data(),write_limit),buffers);
      if(!write_size){done({},0);return;}
      write_done=std::move(done);
      try {
        asio::post(executor,[self=this->shared_from_this()] {
          std::lock_guard lock(self->mutex);self->WriteLocked();
        });
      } catch (...) {
        write_size=0;write_done=nullptr;throw;
      }
    }
    void SubmitRead(asio::mutable_buffer buffer,Completion done) {
      std::lock_guard lock(mutex);
      if(closed){done(asio::error::operation_aborted,0);return;}
      if(read_done){done(asio::error::already_started,0);return;}
      if(!buffer.size()){done({},0);return;}
      read_buffer=buffer;read_done=std::move(done);ReadLocked();
    }
    bool Deliver(const udp::endpoint& source,std::span<const uint8_t> bytes) {
      RequireOwner();std::lock_guard lock(mutex);
      if(closed)return false;
      if(source!=remote)return true;
      if(!channel->HandleReceived(bytes.data(),bytes.size()))FailLocked(ChannelError());
      WriteLocked();return !closed;
    }
    bool Tick() {
      RequireOwner();std::lock_guard lock(mutex);
      if(closed)return false;
      if(!channel->TickRetransmit())FailLocked(ChannelError());
      WriteLocked();return !closed;
    }
    NativeUDPStreamStats Stats() const {
      std::lock_guard lock(mutex);NativeUDPStreamStats result;
      result.open=!closed;result.reading=bool(read_done);result.writing=bool(write_done);
      result.receive_bytes=used;result.receive_capacity=receive.capacity();
      result.pending_packets=channel->pending_count();result.pending_bytes=channel->pending_bytes();
      result.reorder_bytes=channel->received_bytes();return result;
    }
    const std::shared_ptr<udp::socket> socket;
    const udp::endpoint remote;
    const executor_type executor;
    mutable std::mutex mutex;
    std::unique_ptr<ReliableUDPChannel> channel;
    std::vector<uint8_t> receive;
    size_t head=0,used=0,write_size=0;
    const size_t write_limit;
    std::array<uint8_t,kReliableUDP_MaxPayload> write_bytes{};
    asio::mutable_buffer read_buffer;
    Completion read_done,write_done;
    bool closed=false;
  };
  template<class Handler>
  static Completion OnAssociatedExecutor(Handler&& handler,const executor_type& owner) {
    auto target=asio::get_associated_executor(handler,owner);
    // 2026-09-15: auto target_work=asio::make_work_guard(target);
    auto target_work=KeepNativeUDPExecutorAlive(target);
    // 2026-09-15: auto owner_work=asio::make_work_guard(owner);
    auto owner_work=KeepNativeUDPExecutorAlive(owner);
    return [handler=std::forward<Handler>(handler),target,
            target_work=std::move(target_work),owner_work=std::move(owner_work)](Error error,size_t bytes) mutable {
      asio::post(target,[handler=std::move(handler),target_work=std::move(target_work),
                         owner_work=std::move(owner_work),error,bytes]() mutable {
        std::move(handler)(error,bytes);
      });
    };
  }
 public:
  // The listener retains only a weak control handle, so channel entries cannot
  // keep their sessions or pending completions alive after socket destruction.
  class Control {
   public:
    Control()=default;~Control()=default;
    Control(const Control&)=default;Control& operator=(const Control&)=default;
    Control(Control&&)=default;Control& operator=(Control&&)=default;
    bool Deliver(const udp::endpoint& source,std::span<const uint8_t> bytes) const {
      auto state=state_.lock();return state && state->Deliver(source,bytes);
    }
    bool Tick() const {auto state=state_.lock();return state && state->Tick();}
    void Close() const {if(auto state=state_.lock())state->Close();}
    std::optional<NativeUDPStreamStats> Stats() const {
      if(auto state=state_.lock())return state->Stats();return std::nullopt;
    }
   private:
    friend class NativeUDPSocket;
    explicit Control(const std::shared_ptr<State>& state):state_(state){}
    std::weak_ptr<State> state_;
  };

  NativeUDPSocket()=delete;
  // Closed placeholder for an accept error, retaining the correct executor.
  explicit NativeUDPSocket(executor_type executor):executor_(std::move(executor)){}
  NativeUDPSocket(std::shared_ptr<udp::socket> socket,const udp::endpoint& remote,
      executor_type executor,std::optional<ReliableUDPConnection> connection,
      NativeUDPStreamLimits limits={},ReliableUDPChannel::NowFn now=ReliableUDPChannel::Clock::now)
    :executor_(std::move(executor)) {
    limits.Validate();
    if(!socket || !socket->is_open() || !remote.port() || remote.address().is_unspecified() || !now ||
       (connection && std::all_of(connection->begin(),connection->end(),[](uint8_t b){return !b;})))
      throw std::invalid_argument("Invalid native UDP stream endpoint, identity or clock");
    const size_t header=connection ? kReliableUDP_SessionHeaderSize : kReliableUDP_HeaderSize;
    if(limits.datagrams.byte_limit<=header)
      throw std::invalid_argument("UDP stream byte budget cannot retain one data byte");
    const size_t write_limit=std::min(kReliableUDP_MaxPacketSize-header,limits.datagrams.byte_limit-header);
    state_=std::make_shared<State>(std::move(socket),remote,executor_,limits,write_limit);
    if(state_->receive.capacity()>limits.receive_bytes)
      throw std::length_error("UDP stream allocator exceeded receive capacity");
    const auto weak=std::weak_ptr<State>(state_);
    state_->channel=std::make_unique<ReliableUDPChannel>(*state_->socket,remote,
      [weak](const uint8_t* bytes,size_t count) {
        if(auto state=weak.lock())state->DataLocked(bytes,count);
      },limits.datagrams,std::move(now),std::move(connection));
  }
  ~NativeUDPSocket(){if(state_)state_->Close();}
  NativeUDPSocket(const NativeUDPSocket&)=delete;
  NativeUDPSocket& operator=(const NativeUDPSocket&)=delete;
  NativeUDPSocket(NativeUDPSocket&& other) noexcept
    :executor_(other.executor_),state_(std::move(other.state_)){}
  NativeUDPSocket& operator=(NativeUDPSocket&& other) {
    if(this!=&other) {
      if(state_)state_->Close();
      executor_=other.executor_;state_=std::move(other.state_);
    }
    return *this;
  }
  executor_type get_executor() const noexcept {return executor_;}
  bool is_open() const {return state_ && state_->Stats().open;}
  void close(Error& error) {error.clear();if(state_)state_->Close();}
  void close(){Error ignored;close(ignored);}
  Control control() const {return Control(state_);}
  udp::endpoint remote_endpoint() const {
    if(!state_)throw boost::system::system_error(asio::error::bad_descriptor);
    return state_->remote;
  }
  template<class MutableBuffers,class CompletionToken>
  auto async_read_some(const MutableBuffers& buffers,CompletionToken&& token) {
    return asio::async_initiate<CompletionToken,void(Error,size_t)>(
      [state=state_,owner=executor_,buffers](auto&& handler) mutable {
        auto done=OnAssociatedExecutor(std::forward<decltype(handler)>(handler),owner);
        if(!state){done(asio::error::bad_descriptor,0);return;}
        asio::mutable_buffer first;
        for(auto it=asio::buffer_sequence_begin(buffers),end=asio::buffer_sequence_end(buffers);it!=end;++it)
          if(asio::mutable_buffer(*it).size()){first=asio::mutable_buffer(*it);break;}
        state->SubmitRead(first,std::move(done));
      },token);
  }
  template<class ConstBuffers,class CompletionToken>
  auto async_write_some(const ConstBuffers& buffers,CompletionToken&& token) {
    return asio::async_initiate<CompletionToken,void(Error,size_t)>(
      [state=state_,owner=executor_,buffers](auto&& handler) mutable {
        auto done=OnAssociatedExecutor(std::forward<decltype(handler)>(handler),owner);
        if(!state){done(asio::error::bad_descriptor,0);return;}
        state->SubmitWrite(buffers,std::move(done));
      },token);
  }
 private:
  executor_type executor_;
  std::shared_ptr<State> state_;
};
} // namespace frame_sync
