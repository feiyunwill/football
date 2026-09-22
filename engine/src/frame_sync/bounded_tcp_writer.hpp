// Copyright 2026 Google LLC & Contributors
// 2026-09-09: one ordered stream, bounded before posting to the IO executor.
#ifndef GFOOTBALL_FRAME_SYNC_BOUNDED_TCP_WRITER_HPP
#define GFOOTBALL_FRAME_SYNC_BOUNDED_TCP_WRITER_HPP

#include "frame_sync/memory_budget.hpp"
#include <utility>
#include <boost/asio.hpp>
#include <chrono>
#include <deque>
#include <memory>
#include <mutex>

namespace frame_sync {
enum class StreamStatus { Ready, Capacity, InvalidMessage, IoError, WriteTimeout, Closed };

// A shared socket must be a separately owned object (not an alias to its session).
// After handshake, reads and shutdown use this object so all socket operations
// are serialized. External synchronous socket access requires quiescent IO.
class BoundedTCPWriter {
 private:
  using Socket = boost::asio::ip::tcp::socket;
  struct State : std::enable_shared_from_this<State> {
    State(std::shared_ptr<Socket> socket, StreamBudget budget,
          std::chrono::milliseconds timeout)
        : socket(std::move(socket)), budget(budget.message_limit, budget.byte_limit),
          executor(boost::asio::make_strand(this->socket->get_executor())),
          timer(executor), timeout(timeout) {}
    std::shared_ptr<Socket> socket;
    const StreamBudget budget;
    boost::asio::strand<boost::asio::any_io_executor> executor;
    boost::asio::steady_timer timer;
    const std::chrono::milliseconds timeout;
    std::mutex mutex;
    std::deque<std::vector<uint8_t>> waiting;
    std::vector<uint8_t> active;
    size_t bytes = 0;
    bool writing = false;
    bool scheduled = false;
    bool reading = false;
    bool closed = false;
    bool close_posted = false;
    uint64_t generation = 0;
    StreamStatus status = StreamStatus::Ready;

    void DiscardWaiting() {
      for (const auto& message : waiting) bytes -= RetainedBytes(message);
      waiting.clear();
    }
    void CloseSocket() {
      // Called exclusively on executor. Completion retains active until the
      // composed async_write has stopped referencing it.
      boost::system::error_code ignored;
      socket->close(ignored);
      timer.cancel();
    }
    void Close(StreamStatus reason) {
      std::lock_guard lock(mutex);
      if (!closed) {
        closed = true;
        status = reason;
        DiscardWaiting();
      }
      if (close_posted) return;
      boost::asio::post(executor, [self = shared_from_this()] { self->CloseSocket(); });
      close_posted = true;
    }
    bool Send(const void* data, size_t length) {
      std::lock_guard lock(mutex);
      if (closed) return false;
      if (!data || length == 0) { status = StreamStatus::InvalidMessage; return false; }
      if (length > budget.byte_limit - bytes ||
          waiting.size() + size_t(writing) >= budget.message_limit) {
        status = StreamStatus::Capacity;
        return false;
      }
      const auto* begin = static_cast<const uint8_t*>(data);
      std::vector<uint8_t> message(begin, begin + length);
      const auto retained = RetainedBytes(message);
      if (retained > budget.byte_limit - bytes) { status = StreamStatus::Capacity; return false; }
      waiting.push_back(std::move(message));
      bytes += retained;
      if (!scheduled) {
        try {
          boost::asio::post(executor, [self = shared_from_this()] { self->Write(); });
        } catch (...) {
          bytes -= RetainedBytes(waiting.back());
          waiting.pop_back();
          throw;
        }
        scheduled = true;
      }
      status = StreamStatus::Ready;
      return true;
    }
    void Write() {
      std::lock_guard lock(mutex);
      if (closed || waiting.empty()) { scheduled = false; return; }
      active = std::move(waiting.front());
      waiting.pop_front();
      writing = true;
      const auto current_generation = ++generation;
      timer.expires_after(timeout);
      timer.async_wait([self = shared_from_this(), current_generation](boost::system::error_code ec) {
        if (ec) return;
        {
          std::lock_guard lock(self->mutex);
          if (!self->writing || self->generation != current_generation || self->closed) return;
          self->closed = true;
          self->status = StreamStatus::WriteTimeout;
          self->DiscardWaiting();
        }
        self->CloseSocket();
      });
      boost::asio::async_write(*socket, boost::asio::buffer(active),
          boost::asio::bind_executor(executor,
            [self = shared_from_this()](boost::system::error_code ec, size_t sent) {
              bool again = false, failed = false;
              {
                std::lock_guard lock(self->mutex);
                failed = bool(ec) || sent != self->active.size();
                self->bytes -= RetainedBytes(self->active);
                std::vector<uint8_t>().swap(self->active);
                self->writing = false;
                if (failed && !self->closed) {
                  self->closed = true;
                  self->status = StreamStatus::IoError;
                  self->DiscardWaiting();
                }
                again = !self->closed && !self->waiting.empty();
                if (!again) self->scheduled = false;
              }
              self->timer.cancel();
              if (failed) self->CloseSocket();
              else if (again) self->Write();
            }));
    }
  };

 public:
  explicit BoundedTCPWriter(std::shared_ptr<Socket> socket,
                            StreamBudget budget = StreamBudget{},
                            std::chrono::milliseconds timeout = std::chrono::seconds(5)) {
    if (!socket || timeout.count() < 1 || timeout > std::chrono::seconds(30))
      throw std::invalid_argument("TCP writer needs a socket and bounded write timeout");
    state_ = std::make_shared<State>(std::move(socket), budget, timeout);
  }
  ~BoundedTCPWriter() { Close(); }
  BoundedTCPWriter(const BoundedTCPWriter&) = delete;
  BoundedTCPWriter& operator=(const BoundedTCPWriter&) = delete;
  BoundedTCPWriter(BoundedTCPWriter&&) = delete;
  BoundedTCPWriter& operator=(BoundedTCPWriter&&) = delete;

  [[nodiscard]] bool TrySend(const void* data, size_t length) { return state_->Send(data, length); }
  void Close() { state_->Close(StreamStatus::Closed); }
  bool is_closed() const { std::lock_guard lock(state_->mutex); return state_->closed; }
  StreamStatus status() const { std::lock_guard lock(state_->mutex); return state_->status; }
  size_t queued_bytes() const { std::lock_guard lock(state_->mutex); return state_->bytes; }
  size_t queued_messages() const {
    std::lock_guard lock(state_->mutex);
    return state_->waiting.size() + size_t(state_->writing);
  }

  // Caller retains buffer memory in its completion capture. At most one read
  // may be queued/in flight, including while the IO context is not running.
  template<class Completion>
  [[nodiscard]] bool AsyncReadSome(boost::asio::mutable_buffer buffer, Completion completion) {
    auto self = state_;
    std::lock_guard lock(self->mutex);
    if (self->closed || self->reading || buffer.size() == 0) return false;
    boost::asio::post(self->executor, [self, buffer, completion = std::move(completion)]() mutable {
      bool closed;
      { std::lock_guard lock(self->mutex); closed = self->closed; }
      if (closed) {
        { std::lock_guard lock(self->mutex); self->reading = false; }
        completion(boost::asio::error::operation_aborted, 0);
        return;
      }
      self->socket->async_read_some(buffer, boost::asio::bind_executor(self->executor,
          [self, completion = std::move(completion)](boost::system::error_code ec, size_t length) mutable {
            { std::lock_guard lock(self->mutex); self->reading = false; }
            if (ec) self->Close(StreamStatus::IoError);
            completion(ec, length);
          }));
    });
    self->reading = true;
    return true;
  }

 private:
  std::shared_ptr<State> state_;
};
}  // namespace frame_sync
#endif
