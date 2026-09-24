
#pragma once
#include "frame_sync/native_match_contract.hpp"
#include <array>
#include <fstream>
#include <functional>
#include <memory>
#include <span>
#include <stdexcept>
#include <thread>
namespace frame_sync {
// Record exactly the owner's authority/notices, including when no client is
// connected. Transport retransmissions and reconnect bootstrap copies do not
// enter this stream. Enabled only by an explicitly configured recording path.
class NativeAuthorityRecording {
 public:
  NativeAuthorityRecording(const char* file,const NativeMatchContract& match)
      : output_(Open(file,match)),
        owner_(std::this_thread::get_id()) {
    std::array<uint8_t,12> bytes{'F','T','A','C'};
    for(unsigned i=0;i<4;++i)bytes[4+i]=static_cast<uint8_t>(match.seed>>(8*i));
    bytes[8]=static_cast<uint8_t>(match.left);bytes[9]=static_cast<uint8_t>(match.right);
    bytes[10]=NativeMatchContract::kPhysicsSteps&255;
    bytes[11]=(NativeMatchContract::kPhysicsSteps>>8)&255;
    Write(bytes);
  }
  void Record(std::span<const uint8_t> bytes) {
    if(bytes.empty() || (bytes[0]!=3 && bytes[0]!=4 && bytes[0]!=10 && bytes[0]!=11))
      throw std::invalid_argument("Unexpected authority recording packet");
    if(std::this_thread::get_id()!=owner_)
      throw std::runtime_error("Authority recording left frame owner");
    Write(bytes);
  }
 private:
  static std::ofstream Open(const char* file,const NativeMatchContract& match) {
    match.Validate();
    if(!file || !*file)throw std::invalid_argument("Empty authority recording path");
    std::ofstream stream(file,std::ios::binary|std::ios::out|std::ios::noreplace);
    if(!stream)throw std::runtime_error("Cannot exclusively create authority recording");
    return stream;
  }
  void Write(std::span<const uint8_t> bytes) {
    constexpr size_t maximum=64*1024*1024;
    if(bytes.size()>maximum-size_)throw std::length_error("Authority recording exceeds byte budget");
    output_.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
    output_.flush();
    if(!output_)throw std::runtime_error("Authority recording write or flush failed");
    size_+=bytes.size();
  }
  std::ofstream output_;
  const std::thread::id owner_;
  size_t size_=0;
};
inline std::function<void(std::span<const uint8_t>)> OpenNativeAuthorityRecording(
    const char* path,const NativeMatchContract& match) {
  auto writer=std::make_shared<NativeAuthorityRecording>(path,match);
  return [writer=std::move(writer)](std::span<const uint8_t> bytes){writer->Record(bytes);};
}
}
