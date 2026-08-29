// Copyright 2026 Google LLC & Contributors
// FixedPoint 单元测试：验证定点数运算正确性与跨平台确定性
//
// 2026-08-30: 重建 — 原文件损坏（二进制数据），迁移到 gtest 框架

#include "base/math/fixed_point.hpp"

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>

using namespace blunted;

// ========== 构造测试 ==========

TEST(FixedPointTest, DefaultConstruction) {
  FixedPoint zero;
  EXPECT_FLOAT_EQ(zero.ToFloat(), 0.0f);
}

TEST(FixedPointTest, IntConstruction) {
  FixedPoint from_int(5);
  EXPECT_FLOAT_EQ(from_int.ToFloat(), 5.0f);

  FixedPoint neg(-7);
  EXPECT_FLOAT_EQ(neg.ToFloat(), -7.0f);
}

TEST(FixedPointTest, FloatConstruction) {
  FixedPoint from_float(3.14f);
  EXPECT_NEAR(from_float.ToFloat(), 3.14f, 0.001f);
}

TEST(FixedPointTest, FromRaw) {
  FixedPoint one = FixedPoint::FromRaw(65536);  // 1.0 in Q16.16
  EXPECT_FLOAT_EQ(one.ToFloat(), 1.0f);

  FixedPoint half = FixedPoint::FromRaw(32768);  // 0.5
  EXPECT_FLOAT_EQ(half.ToFloat(), 0.5f);
}

TEST(FixedPointTest, Constants) {
  EXPECT_FLOAT_EQ(FixedPoint::Zero().ToFloat(), 0.0f);
  EXPECT_FLOAT_EQ(FixedPoint::One().ToFloat(), 1.0f);
  EXPECT_FLOAT_EQ(FixedPoint::Half().ToFloat(), 0.5f);
  EXPECT_NEAR(FixedPoint::Pi().ToFloat(), 3.14159265f, 0.001f);
}

TEST(FixedPointTest, ToRaw) {
  FixedPoint a(5);
  EXPECT_EQ(a.ToRaw(), 5 << 16);
}

// ========== 算术测试 ==========

TEST(FixedPointTest, Addition) {
  FixedPoint a(3);
  FixedPoint b(2);
  FixedPoint sum = a + b;
  EXPECT_FLOAT_EQ(sum.ToFloat(), 5.0f);
}

TEST(FixedPointTest, Subtraction) {
  FixedPoint a(3);
  FixedPoint b(2);
  FixedPoint diff = a - b;
  EXPECT_FLOAT_EQ(diff.ToFloat(), 1.0f);
}

TEST(FixedPointTest, Multiplication) {
  FixedPoint a(3);
  FixedPoint b(2);
  FixedPoint prod = a * b;
  EXPECT_FLOAT_EQ(prod.ToFloat(), 6.0f);
}

TEST(FixedPointTest, Division) {
  FixedPoint a(3);
  FixedPoint b(2);
  FixedPoint quot = a / b;
  EXPECT_FLOAT_EQ(quot.ToFloat(), 1.5f);
}

TEST(FixedPointTest, CompoundAssignment) {
  FixedPoint c(10);
  c += FixedPoint(5);
  EXPECT_FLOAT_EQ(c.ToFloat(), 15.0f);

  c -= FixedPoint(3);
  EXPECT_FLOAT_EQ(c.ToFloat(), 12.0f);

  c *= FixedPoint(2);
  EXPECT_FLOAT_EQ(c.ToFloat(), 24.0f);

  c /= FixedPoint(4);
  EXPECT_FLOAT_EQ(c.ToFloat(), 6.0f);
}

// ========== 小数精度测试 ==========

TEST(FixedPointTest, FractionalArithmetic) {
  FixedPoint half(0.5f);
  FixedPoint quarter(0.25f);
  FixedPoint result = half + quarter;
  EXPECT_NEAR(result.ToFloat(), 0.75f, 0.002f);

  FixedPoint a(1.5f);
  FixedPoint b(2.5f);
  FixedPoint prod = a * b;
  EXPECT_NEAR(prod.ToFloat(), 3.75f, 0.002f);
}

TEST(FixedPointTest, DivisionPrecision) {
  FixedPoint div_result = FixedPoint(1.0f) / FixedPoint(3.0f);
  EXPECT_NEAR(div_result.ToFloat(), 0.3333f, 0.002f);
}

// ========== 比较运算测试 ==========

TEST(FixedPointTest, Comparison) {
  FixedPoint a(5);
  FixedPoint b(5);
  FixedPoint c(3);

  EXPECT_TRUE(a == b);
  EXPECT_FALSE(a == c);
  EXPECT_TRUE(a != c);
  EXPECT_TRUE(c < a);
  EXPECT_TRUE(a > c);
  EXPECT_TRUE(a <= b);
  EXPECT_TRUE(a >= b);
}

// ========== 一元运算测试 ==========

TEST(FixedPointTest, Negation) {
  FixedPoint a(5);
  FixedPoint neg = -a;
  EXPECT_FLOAT_EQ(neg.ToFloat(), -5.0f);
}

TEST(FixedPointTest, Abs) {
  FixedPoint b(-3);
  EXPECT_FLOAT_EQ(b.Abs().ToFloat(), 3.0f);

  FixedPoint c(7);
  EXPECT_FLOAT_EQ(c.Abs().ToFloat(), 7.0f);
}

// ========== 三角函数测试 ==========

TEST(FixedPointTest, SinZero) {
  FixedPoint sin0 = FixedPoint::Sin(FixedPoint::Zero());
  EXPECT_NEAR(sin0.ToFloat(), 0.0f, 0.01f);
}

TEST(FixedPointTest, SinHalfPi) {
  FixedPoint sin_half_pi = FixedPoint::Sin(FixedPoint::HalfPi());
  EXPECT_NEAR(sin_half_pi.ToFloat(), 1.0f, 0.02f);
}

TEST(FixedPointTest, CosZero) {
  FixedPoint cos0 = FixedPoint::Cos(FixedPoint::Zero());
  EXPECT_NEAR(cos0.ToFloat(), 1.0f, 0.01f);
}

TEST(FixedPointTest, CosPi) {
  FixedPoint cos_pi = FixedPoint::Cos(FixedPoint::Pi());
  EXPECT_NEAR(cos_pi.ToFloat(), -1.0f, 0.02f);
}

TEST(FixedPointTest, SinPiOver4) {
  FixedPoint angle_pi_4 = FixedPoint::HalfPi() / FixedPoint(2);
  FixedPoint sin_pi_4 = FixedPoint::Sin(angle_pi_4);
  EXPECT_NEAR(sin_pi_4.ToFloat(), 0.7071f, 0.02f);
}

// ========== 平方根测试 ==========

TEST(FixedPointTest, Sqrt4) {
  FixedPoint sqrt4 = FixedPoint::Sqrt(FixedPoint(4));
  EXPECT_NEAR(sqrt4.ToFloat(), 2.0f, 0.02f);
}

TEST(FixedPointTest, Sqrt9) {
  FixedPoint sqrt9 = FixedPoint::Sqrt(FixedPoint(9));
  EXPECT_NEAR(sqrt9.ToFloat(), 3.0f, 0.02f);
}

TEST(FixedPointTest, Sqrt2) {
  FixedPoint sqrt2 = FixedPoint::Sqrt(FixedPoint(2));
  EXPECT_NEAR(sqrt2.ToFloat(), 1.4142f, 0.02f);
}

TEST(FixedPointTest, SqrtZero) {
  FixedPoint sqrt0 = FixedPoint::Sqrt(FixedPoint::Zero());
  EXPECT_FLOAT_EQ(sqrt0.ToFloat(), 0.0f);
}

TEST(FixedPointTest, SqrtNegative) {
  // sqrt of negative → 0
  FixedPoint sqrt_neg = FixedPoint::Sqrt(FixedPoint(-1));
  EXPECT_FLOAT_EQ(sqrt_neg.ToFloat(), 0.0f);
}

// ========== 跨平台确定性测试 ==========

TEST(FixedPointTest, AdditionDeterminism) {
  FixedPoint a(3.14159f);
  FixedPoint b(2.71828f);

  FixedPoint sum1 = a + b;
  FixedPoint sum2 = a + b;
  EXPECT_EQ(sum1.ToRaw(), sum2.ToRaw());
}

TEST(FixedPointTest, MultiplicationDeterminism) {
  FixedPoint a(3.14159f);
  FixedPoint b(2.71828f);

  FixedPoint prod1 = a * b;
  FixedPoint prod2 = a * b;
  EXPECT_EQ(prod1.ToRaw(), prod2.ToRaw());
}

TEST(FixedPointTest, DivisionDeterminism) {
  FixedPoint a(3.14159f);
  FixedPoint b(2.71828f);

  FixedPoint div1 = a / b;
  FixedPoint div2 = a / b;
  EXPECT_EQ(div1.ToRaw(), div2.ToRaw());
}

TEST(FixedPointTest, SinDeterminism) {
  FixedPoint a(1.23456f);

  FixedPoint sin1 = FixedPoint::Sin(a);
  FixedPoint sin2 = FixedPoint::Sin(a);
  EXPECT_EQ(sin1.ToRaw(), sin2.ToRaw());
}

// ========== 整数/小数分解测试 ==========

TEST(FixedPointTest, IntegerFraction) {
  FixedPoint a(5.75f);
  EXPECT_EQ(a.Integer(), 5);
  EXPECT_GT(a.Fraction(), 0);
}
