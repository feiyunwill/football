// 2026-09-15: actual socket, ownership generation and opening-barrier contracts.
// 2026-09-15: use the canonical socket fixture.
// #include "seat_fixture.hpp"
#include "fixtures/native_loading_fixture.inc"
fs::NativeRecoveryGrant load(Peer& peer,bool receipt=true) {
 peer.send(fs::pack_recovery_load_hello());const auto session=peer.session();
 require(session.loading && !session.restoring,"Opening admission missing");
 if(receipt)peer.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadReceipt,session.grant));
 return session.grant;
}
void cancelled(Peer& peer,const fs::NativeRecoveryGrant& expected) {
 const auto proof=fs::decode_recovery_load_control(peer.kind(fs::NativeRecoveryKind::LoadCancelled),
                                                  fs::NativeRecoveryKind::LoadCancelled);
 require(proof && proof->slot==expected.slot && proof->generation==expected.generation &&
         fs::native_secret_equal(proof->match,expected.match) &&
         fs::native_secret_equal(proof->secret,expected.secret),"Cancellation receipt ownership differs");
}
fs::NativeRecoveryPacket joined(std::initializer_list<fs::NativeRecoveryPacket> packets) {
 fs::NativeRecoveryPacket out;
 for(const auto& p:packets) {
  require(out.size+p.size<=out.bytes.size(),"Joined packet bound");
  std::copy(p.view().begin(),p.view().end(),out.bytes.begin()+out.size);out.size+=p.size;
 }
 return out;
}
void wire_contract() {
 Server server(2s);Peer peer(server.port());const auto grant=load(peer);
 for(auto kind:{fs::NativeRecoveryKind::LoadCancel,fs::NativeRecoveryKind::LoadCancelled}) {
  const auto packet=fs::pack_recovery_load_control(kind,grant);
  require(packet.size==68,"Cancellation wire size changed");
  require(fs::decode_recovery_load_control(packet.view(),kind).has_value(),"Grant roundtrip failed");
  for(size_t n=0;n<packet.size;++n) {
   require(fs::native_recovery_wire::record_size(packet.view().first(n))==0,"Prefix rejected or parsed early");
   require(!fs::decode_recovery_load_control(packet.view().first(n),kind),"Truncated grant accepted");
  }
  for(size_t n=1;n<10;++n) {
   auto bad=packet;bad.bytes[n]^=1;
   require(fs::native_recovery_wire::record_size(bad.view())==-1,"Malformed fixed header accepted");
  }
  auto extra=packet;extra.bytes[extra.size++]=0;
  require(!fs::decode_recovery_load_control(extra.view(),kind),"Trailing byte accepted");
  require(fs::native_recovery_wire::record_size(joined({packet,packet}).view())==68,"Coalesced boundary lost");
  require(!fs::decode_recovery_load_control(packet.view(),fs::NativeRecoveryKind::LoadReceipt),"Kind confusion");
 }
 auto invalid=grant;invalid.generation=0;bool rejected=false;
 try{fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,invalid);}
 catch(const std::invalid_argument&){rejected=true;}
 require(rejected,"Zero generation packed");
 server.check();
}
void fragment_and_reuse(bool receipt) {
 Server server(2s);Peer first(server.port());const auto old=load(first,receipt);
 const auto packet=fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,old);
 for(size_t n=0;n<packet.size;++n) {
  fs::NativeRecoveryPacket part;part.bytes[0]=packet.bytes[n];part.size=1;first.send(part);
 }
 cancelled(first,old);
 require(server.stats().loading_cancellations==1 && server.stats().next_frame==0,"Cancel did not release before receipt");
 Peer replacement(server.port());const auto fresh=load(replacement);
 require(fresh.slot==old.slot && fresh.generation>old.generation &&
         !fs::native_secret_equal(fresh.secret,old.secret),"Fresh admission inherited cancelled credential");
 Peer replay(server.port());replay.send(fs::pack_recovery_resume(old));replay.reject(fs::NativeRecoveryReject::Unauthorized);
 require(server.stats().loading_cancellations==1,"Replay mutated admission count");
 replacement.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,fresh));cancelled(replacement,fresh);
 require(server.stats().loading_cancellations==2,"Replacement cannot cancel");
 server.check();
}
void completion_race() {
 Server server(2s);Peer peer(server.port());const auto grant=load(peer);
 fs::NativeRecoveryReady ready;ready.grant=grant;ready.state_hash=7;
 peer.send(joined({fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadComplete,grant),
                   fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,grant),
                   fs::pack_recovery_ready(ready)}));
 cancelled(peer,grant);
 require(server.stats().loading_cancellations==1 && server.stats().next_frame==0,"Coalesced late Ready started match");
 Peer replacement(server.port());require(load(replacement).slot==grant.slot,"Cancelled completed loader retained seat");
 server.check();
}
void stale_generation() {
 Server server(2s);Peer old(server.port());const auto first=load(old);
 Peer newer(server.port());
 newer.send(joined({fs::pack_recovery_resume(first),
                    fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,first)}));
 const auto second=newer.session().grant;newer.reject(fs::NativeRecoveryReject::Unauthorized);
 require(second.generation>first.generation && server.stats().loading_cancellations==0,
         "Stale proof released newly rotated ownership");
 Peer other(server.port());const auto other_grant=load(other);
 require(other_grant.slot!=first.slot,"Stale cancellation freed another generation");
 Peer latest(server.port());latest.send(fs::pack_recovery_resume(second));const auto third=latest.session().grant;
 require(third.slot==first.slot && third.generation>second.generation,"Latest owner cannot resume retained admission");
 // No LoadReceipt: the current pending capability itself proves cancellation ownership.
 latest.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,third));cancelled(latest,third);
 require(server.stats().loading_cancellations==1,"Pending generation could not cancel");
 Peer replacement(server.port());require(load(replacement).slot==first.slot,"Latest generation did not free exact seat");
 server.check();
}
void foreign_proofs(unsigned variant) {
 Server server(2s);Peer victim(server.port()),attacker(server.port());
 const auto target=load(victim),own=load(attacker);
 auto forged=target;
 if(variant==0)forged.secret[0]^=1;
 if(variant==1)forged.match[0]^=1;
 if(variant==2)++forged.generation;
 if(variant==3)forged.slot=own.slot;
 attacker.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,forged));
 attacker.reject(fs::NativeRecoveryReject::Unauthorized);
 require(server.stats().loading_cancellations==0,"Foreign proof released an admission");
 victim.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,target));cancelled(victim,target);
 require(server.stats().loading_cancellations==1,"Foreign proof damaged valid owner");
 server.check();
}
void no_grant_cannot_cancel() {
 Server server(2s);Peer victim(server.port());const auto grant=load(victim);
 Peer outsider(server.port());outsider.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,grant));
 outsider.reject(fs::NativeRecoveryReject::Unauthorized);
 require(server.stats().loading_cancellations==0,"Unidentified socket cancelled a copied grant");
 victim.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,grant));cancelled(victim,grant);
 server.check();
}
void starts_other_player() {
 Server server(2s);Peer slow(server.port()),fast(server.port());
 const auto a=load(slow),b=load(fast);
 fast.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadComplete,b));fast.ready(b);
 fast.kind(fs::NativeRecoveryKind::Accepted);
 require(server.stats().next_frame==0,"Opening barrier missing");
 slow.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,a));cancelled(slow,a);
 until([&]{return server.stats().next_frame>0;},"Cancelled loader retained opening barrier");
 require(server.stats().loading_cancellations==1 && server.stats().loading_timeouts==0,"Timeout substituted for release");
 server.check();
}
void started_match_keeps_identity() {
 Server server(2s);Peer first(server.port());const auto grant=load(first);
 first.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadComplete,grant));first.ready(grant);
 first.kind(fs::NativeRecoveryKind::Accepted);
 until([&]{return server.stats().next_frame>0;},"No started match");
 first.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,grant));
 first.reject(fs::NativeRecoveryReject::InvalidState);
 require(server.stats().loading_cancellations==0,"Started slot released as a new admission");
 Peer resumed(server.port());resumed.send(fs::pack_recovery_resume(grant));const auto restored=resumed.session();
 require(restored.restoring && !restored.loading && restored.grant.slot==grant.slot,"Started credential was revoked");
 server.check();
}
// 2026-09-15: complete coalesced terminal records survive FIN; truncated records still fail.
void buffered_terminal_records(bool truncated) {
 asio::io_context io;tcp::acceptor acceptor(io,{asio::ip::address_v4::loopback(),0});
 std::exception_ptr sender_error;
 std::jthread sender([&] {
  try {
   auto socket=acceptor.accept();
   auto packet=joined({fs::pack_recovery_rejected(fs::NativeRecoveryReject::Unauthorized),
                       fs::pack_recovery_rejected(fs::NativeRecoveryReject::InvalidState)});
   if(truncated)--packet.size;
   asio::write(socket,asio::buffer(packet.bytes.data(),packet.size));
   socket.shutdown(tcp::socket::shutdown_send);
  }catch(...){sender_error=std::current_exception();}
 });
 Peer peer(acceptor.local_endpoint().port());
 sender.join();if(sender_error)std::rethrow_exception(sender_error);
 peer.wait_for_fin();
 peer.reject(fs::NativeRecoveryReject::Unauthorized);
 if(!truncated)peer.reject(fs::NativeRecoveryReject::InvalidState);
 else {
  bool rejected=false;
  try{peer.reject(fs::NativeRecoveryReject::InvalidState);}
  catch(const std::runtime_error& error){
   rejected=std::string(error.what()).find("Peer read closed before expected packet")!=std::string::npos;
  }
  require(rejected,"Truncated terminal control was accepted");
 }
}
int main(int,char**) {
 try {
  buffered_terminal_records(false);buffered_terminal_records(true);
  wire_contract();fragment_and_reuse(false);fragment_and_reuse(true);completion_race();stale_generation();
  for(unsigned variant=0;variant<4;++variant)foreign_proofs(variant);
  no_grant_cannot_cancel();starts_other_player();started_match_keeps_identity();
  std::cout<<"{\"passed\":true,\"checks\":14,\"ownership_checks\":12,\"stream_terminal_checks\":2,\"assertions\":"<<assertions
   <<",\"skipped\":0,\"real_tcp\":true,\"frame_owner_checked\":true,\"actual_gameenv\":false}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
