// Copyright 2026 Google LLC & Contributors
// Unit tests for NetworkDiagnostics (ms-17.5)

#include "frame_sync/network_diagnostics.hpp"

#include <gtest/gtest.h>
#include <cmath>

namespace frame_sync {
namespace {

TEST(NetworkDiagnosticsTest, InitialState) {
  NetworkDiagnostics diag;
  auto report = diag.GetReport();
  EXPECT_DOUBLE_EQ(report.smoothed_rtt_ms, 0.0);
  EXPECT_DOUBLE_EQ(report.jitter_ms, 0.0);
  EXPECT_DOUBLE_EQ(report.packet_loss_pct, 0.0);
  EXPECT_DOUBLE_EQ(report.prediction_accuracy, 1.0);
  EXPECT_EQ(report.quality, NetworkQuality::kExcellent);
  EXPECT_EQ(report.quality_str, "Excellent");
}

TEST(NetworkDiagnosticsTest, ExcellentQuality) {
  NetworkDiagnostics diag;
  diag.Update(30.0, 2.0, 0.95, 0, 0, 100);
  EXPECT_EQ(diag.GetQuality(), NetworkQuality::kExcellent);
  EXPECT_LT(diag.GetSmoothedRTT(), 50.0);
}

TEST(NetworkDiagnosticsTest, GoodQuality) {
  NetworkDiagnostics diag;
  diag.Update(75.0, 8.0, 0.90, 0, 1, 100);
  EXPECT_EQ(diag.GetQuality(), NetworkQuality::kGood);
}

TEST(NetworkDiagnosticsTest, FairQuality) {
  NetworkDiagnostics diag;
  diag.Update(150.0, 20.0, 0.80, 0, 3, 100);
  EXPECT_EQ(diag.GetQuality(), NetworkQuality::kFair);
}

TEST(NetworkDiagnosticsTest, PoorQuality) {
  NetworkDiagnostics diag;
  diag.Update(250.0, 35.0, 0.60, 0, 5, 100);
  EXPECT_EQ(diag.GetQuality(), NetworkQuality::kPoor);
}

TEST(NetworkDiagnosticsTest, CriticalQuality) {
  NetworkDiagnostics diag;
  diag.Update(600.0, 5.0, 0.30, 0, 10, 100);
  EXPECT_EQ(diag.GetQuality(), NetworkQuality::kCritical);
}

TEST(NetworkDiagnosticsTest, CriticalByPacketLoss) {
  NetworkDiagnostics diag;
  diag.Update(50.0, 2.0, 0.90, 15, 0, 100);
  EXPECT_EQ(diag.GetQuality(), NetworkQuality::kCritical);
}

TEST(NetworkDiagnosticsTest, SmoothedRTT) {
  NetworkDiagnostics diag;
  // Feed several RTT samples
  diag.Update(100.0, 5.0, 0.9, 0, 0, 10);
  diag.Update(200.0, 5.0, 0.9, 0, 0, 20);
  diag.Update(50.0, 5.0, 0.9, 0, 0, 30);
  // Smoothed should be average of 100, 200, 50 = 116.67
  EXPECT_NEAR(diag.GetSmoothedRTT(), 116.67, 1.0);
}

TEST(NetworkDiagnosticsTest, FormatOverlay) {
  NetworkDiagnostics diag;
  diag.Update(80.0, 10.0, 0.85, 2, 3, 100);
  std::string overlay = diag.FormatOverlay();
  EXPECT_FALSE(overlay.empty());
  EXPECT_NE(overlay.find("RTT"), std::string::npos);
  EXPECT_NE(overlay.find("Jitter"), std::string::npos);
  EXPECT_NE(overlay.find("Pred"), std::string::npos);
}

TEST(NetworkDiagnosticsTest, QualityString) {
  EXPECT_STREQ(NetworkDiagnostics::QualityToString(NetworkQuality::kExcellent), "Excellent");
  EXPECT_STREQ(NetworkDiagnostics::QualityToString(NetworkQuality::kGood), "Good");
  EXPECT_STREQ(NetworkDiagnostics::QualityToString(NetworkQuality::kFair), "Fair");
  EXPECT_STREQ(NetworkDiagnostics::QualityToString(NetworkQuality::kPoor), "Poor");
  EXPECT_STREQ(NetworkDiagnostics::QualityToString(NetworkQuality::kCritical), "Critical");
}

TEST(NetworkDiagnosticsTest, PacketLossEstimate) {
  NetworkDiagnostics diag;
  diag.Update(50.0, 5.0, 0.9, 10, 0, 100);
  EXPECT_NEAR(diag.GetPacketLoss(), 10.0, 0.1);
}

}  // namespace
}  // namespace frame_sync
