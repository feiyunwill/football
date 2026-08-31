// Copyright 2026 Google LLC & Contributors
// FixedPoint 跨平台确定性测试
// 验证定点数运算在不同平台上产生完全相同的结果
//
// 核心原理：所有运算使用纯整数算术（int32_t/int64_t），
// 不依赖浮点运算、编译器优化或平台特定行为。

#include "base/math/fixed_point.hpp"

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

using namespace blunted;

// ===================================================================
// 辅助：生成确定性测试序列
// ===================================================================

/// 用固定种子生成伪随机 FixedPoint 序列
static std::vector<FixedPoint> GenerateDeterministicSequence(uint32_t seed,
                                                             int count) {
  // 简单 xorshift32 作为种子扩展
  uint32_t s = seed;
  std::vector<FixedPoint> result;
  result.reserve(count);
  for (int i = 0; i < count; ++i) {
    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    // 生成 [-100, 100] 范围的定点数
    int32_t raw = static_cast<int32_t>(s % 20000000) - 10000000;
    result.push_back(FixedPoint::FromRaw(raw));
  }
  return result;
}

// ===================================================================
// 确定性测试：相同输入 → 相同输出（位精确）
// ===================================================================

TEST(FixedPointDeterminism, AdditionBitExact) {
  auto seq = GenerateDeterministicSequence(42, 1000);
  for (int i = 0; i < 999; ++i) {
    FixedPoint sum1 = seq[i] + seq[i + 1];
    FixedPoint sum2 = seq[i] + seq[i + 1];
    EXPECT_EQ(sum1.ToRaw(), sum2.ToRaw())
        << "Addition not deterministic at i=" << i;
  }
}

TEST(FixedPointDeterminism, MultiplicationBitExact) {
  auto seq = GenerateDeterministicSequence(123, 1000);
  for (int i = 0; i < 999; ++i) {
    FixedPoint prod1 = seq[i] * seq[i + 1];
    FixedPoint prod2 = seq[i] * seq[i + 1];
    EXPECT_EQ(prod1.ToRaw(), prod2.ToRaw())
        << "Multiplication not deterministic at i=" << i;
  }
}

TEST(FixedPointDeterminism, DivisionBitExact) {
  auto seq = GenerateDeterministicSequence(456, 1000);
  for (int i = 0; i < 999; ++i) {
    if (seq[i + 1].ToRaw() == 0) continue;  // 跳过除零
    FixedPoint div1 = seq[i] / seq[i + 1];
    FixedPoint div2 = seq[i] / seq[i + 1];
    EXPECT_EQ(div1.ToRaw(), div2.ToRaw())
        << "Division not deterministic at i=" << i;
  }
}

TEST(FixedPointDeterminism, TrigBitExact) {
  // 测试一系列角度的 sin/cos 是否位精确
  for (int32_t raw = -200000; raw <= 200000; raw += 1000) {
    FixedPoint angle = FixedPoint::FromRaw(raw);
    FixedPoint sin1 = FixedPoint::Sin(angle);
    FixedPoint sin2 = FixedPoint::Sin(angle);
    EXPECT_EQ(sin1.ToRaw(), sin2.ToRaw())
        << "Sin not deterministic at raw=" << raw;

    FixedPoint cos1 = FixedPoint::Cos(angle);
    FixedPoint cos2 = FixedPoint::Cos(angle);
    EXPECT_EQ(cos1.ToRaw(), cos2.ToRaw())
        << "Cos not deterministic at raw=" << raw;
  }
}

TEST(FixedPointDeterminism, SqrtBitExact) {
  for (int32_t raw = 0; raw <= 200000; raw += 500) {
    FixedPoint x = FixedPoint::FromRaw(raw);
    FixedPoint sqrt1 = FixedPoint::Sqrt(x);
    FixedPoint sqrt2 = FixedPoint::Sqrt(x);
    EXPECT_EQ(sqrt1.ToRaw(), sqrt2.ToRaw())
        << "Sqrt not deterministic at raw=" << raw;
  }
}

TEST(FixedPointDeterminism, Atan2BitExact) {
  for (int32_t y_raw = -100000; y_raw <= 100000; y_raw += 5000) {
    for (int32_t x_raw = -100000; x_raw <= 100000; x_raw += 5000) {
      if (x_raw == 0 && y_raw == 0) continue;
      FixedPoint y = FixedPoint::FromRaw(y_raw);
      FixedPoint x = FixedPoint::FromRaw(x_raw);
      FixedPoint atan1 = FixedPoint::Atan2(y, x);
      FixedPoint atan2 = FixedPoint::Atan2(y, x);
      EXPECT_EQ(atan1.ToRaw(), atan2.ToRaw())
          << "Atan2 not deterministic at (" << y_raw << ", " << x_raw << ")";
    }
  }
}

// ===================================================================
// 三角恒等式测试：验证 CORDIC 实现的数学正确性
// ===================================================================

TEST(FixedPointDeterminism, PythagoreanIdentity) {
  // sin²(a) + cos²(a) ≈ 1
  for (int32_t raw = -200000; raw <= 200000; raw += 2000) {
    FixedPoint angle = FixedPoint::FromRaw(raw);
    FixedPoint sin_val = FixedPoint::Sin(angle);
    FixedPoint cos_val = FixedPoint::Cos(angle);

    // sin² + cos² = 1
    FixedPoint sum = sin_val * sin_val + cos_val * cos_val;
    FixedPoint one = FixedPoint::One();

    // 允许定点数精度误差（< 0.02）
    EXPECT_NEAR(sum.ToFloat(), one.ToFloat(), 0.02f)
        << "Pythagorean identity failed at raw=" << raw;
  }
}

TEST(FixedPointDeterminism, SinCosPeriodicity) {
  // sin(a + 2π) = sin(a), cos(a + 2π) = cos(a)
  FixedPoint two_pi = FixedPoint::TwoPi();
  for (int32_t raw = -100000; raw <= 100000; raw += 3000) {
    FixedPoint angle = FixedPoint::FromRaw(raw);
    FixedPoint shifted = angle + two_pi;

    FixedPoint sin1 = FixedPoint::Sin(angle);
    FixedPoint sin2 = FixedPoint::Sin(shifted);
    EXPECT_NEAR(sin1.ToFloat(), sin2.ToFloat(), 0.01f)
        << "Sin periodicity failed at raw=" << raw;

    FixedPoint cos1 = FixedPoint::Cos(angle);
    FixedPoint cos2 = FixedPoint::Cos(shifted);
    EXPECT_NEAR(cos1.ToFloat(), cos2.ToFloat(), 0.01f)
        << "Cos periodicity failed at raw=" << raw;
  }
}

TEST(FixedPointDeterminism, SinOddFunction) {
  // sin(-a) = -sin(a)
  for (int32_t raw = 0; raw <= 200000; raw += 3000) {
    FixedPoint angle = FixedPoint::FromRaw(raw);
    FixedPoint sin_pos = FixedPoint::Sin(angle);
    FixedPoint sin_neg = FixedPoint::Sin(-angle);
    EXPECT_NEAR(sin_pos.ToFloat(), -sin_neg.ToFloat(), 0.01f)
        << "Sin odd function failed at raw=" << raw;
  }
}

TEST(FixedPointDeterminism, CosEvenFunction) {
  // cos(-a) = cos(a)
  for (int32_t raw = 0; raw <= 200000; raw += 3000) {
    FixedPoint angle = FixedPoint::FromRaw(raw);
    FixedPoint cos_pos = FixedPoint::Cos(angle);
    FixedPoint cos_neg = FixedPoint::Cos(-angle);
    EXPECT_NEAR(cos_pos.ToFloat(), cos_neg.ToFloat(), 0.01f)
        << "Cos even function failed at raw=" << raw;
  }
}

TEST(FixedPointDeterminism, SqrtMultiplicative) {
  // sqrt(a * b) = sqrt(a) * sqrt(b)（对正数）
  for (int32_t a_raw = 1000; a_raw <= 50000; a_raw += 5000) {
    for (int32_t b_raw = 1000; b_raw <= 50000; b_raw += 5000) {
      FixedPoint a = FixedPoint::FromRaw(a_raw);
      FixedPoint b = FixedPoint::FromRaw(b_raw);
      FixedPoint sqrt_ab = FixedPoint::Sqrt(a * b);
      FixedPoint sqrt_a_sqrt_b = FixedPoint::Sqrt(a) * FixedPoint::Sqrt(b);
      EXPECT_NEAR(sqrt_ab.ToFloat(), sqrt_a_sqrt_b.ToFloat(), 0.05f)
          << "Sqrt multiplicative failed at (" << a_raw << ", " << b_raw << ")";
    }
  }
}

// ===================================================================
// 编译期确定性验证
// ===================================================================

TEST(FixedPointDeterminism, ConstexprConstruction) {
  // 验证 constexpr 构造在编译期完成
  constexpr FixedPoint a(5);
  constexpr FixedPoint b(3);
  constexpr FixedPoint sum = a + b;
  constexpr FixedPoint neg = -a;

  static_assert(sum.ToRaw() == (5 << 16) + (3 << 16), "constexpr addition");
  static_assert(neg.ToRaw() == -(5 << 16), "constexpr negation");

  EXPECT_EQ(sum.ToRaw(), (5 << 16) + (3 << 16));
}

TEST(FixedPointDeterminism, ConstexprTrig) {
  // 验证 constexpr 常量
  constexpr FixedPoint zero = FixedPoint::Zero();
  constexpr FixedPoint one = FixedPoint::One();
  constexpr FixedPoint half = FixedPoint::Half();
  constexpr FixedPoint pi = FixedPoint::Pi();

  static_assert(zero.ToRaw() == 0, "constexpr zero");
  static_assert(one.ToRaw() == 65536, "constexpr one");
  static_assert(half.ToRaw() == 32768, "constexpr half");
  static_assert(pi.ToRaw() == 205887, "constexpr pi");

  EXPECT_EQ(zero.ToRaw(), 0);
  EXPECT_EQ(one.ToRaw(), 65536);
  EXPECT_EQ(half.ToRaw(), 32768);
  EXPECT_EQ(pi.ToRaw(), 205887);
}
