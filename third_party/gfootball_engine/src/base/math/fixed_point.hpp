// Copyright 2026 Google LLC & Contributors
// 定点数实现：确保跨平台浮点运算一致
//
// 2026-08-30: 重写三角函数为 CORDIC 算法，sqrt 为整数 Newton 法
//            所有运算纯整数，无 float 转换，保证跨平台确定性

#ifndef _HPP_BASE_MATH_FIXED_POINT
#define _HPP_BASE_MATH_FIXED_POINT

#include <cstdint>
#include <cstring>

namespace blunted {

/// 定点数类：使用 Q16.16 格式（16位整数 + 16位小数）
/// 用于帧同步中需要跨平台确定性的场景
///
/// 设计原则：
/// - 所有运算使用纯整数算术，避免浮点转换
/// - 三角函数使用 CORDIC 算法（16次迭代，误差 < 0.001）
/// - sqrt 使用整数 Newton 法（无浮点依赖）
/// - constexpr 构造，零运行时开销
class FixedPoint {
 public:
  // ===== 构造函数 =====

  constexpr FixedPoint() : value_(0) {}
  constexpr explicit FixedPoint(int32_t integer)
      : value_(static_cast<int32_t>(static_cast<int64_t>(integer)
                                    << kFractionalBits)) {}
  constexpr explicit FixedPoint(float f)
      : value_(static_cast<int32_t>(f * static_cast<float>(kOneRaw))) {}
  constexpr explicit FixedPoint(double d)
      : value_(static_cast<int32_t>(d * static_cast<double>(kOneRaw))) {}

  // 从原始值构造
  static constexpr FixedPoint FromRaw(int32_t raw) {
    FixedPoint fp;
    fp.value_ = raw;
    return fp;
  }

  // ===== 转换 =====

  constexpr float ToFloat() const {
    return static_cast<float>(value_) /
           static_cast<float>(kOneRaw);
  }
  constexpr double ToDouble() const {
    return static_cast<double>(value_) /
           static_cast<double>(kOneRaw);
  }
  constexpr int32_t ToRaw() const { return value_; }
  constexpr int32_t Integer() const { return value_ >> kFractionalBits; }
  constexpr int32_t Fraction() const { return value_ & kFractionalMask; }

  // ===== 基本算术 =====

  constexpr FixedPoint operator+(const FixedPoint& rhs) const {
    return FromRaw(value_ + rhs.value_);
  }
  constexpr FixedPoint operator-(const FixedPoint& rhs) const {
    return FromRaw(value_ - rhs.value_);
  }
  constexpr FixedPoint operator*(const FixedPoint& rhs) const {
    return FromRaw(static_cast<int32_t>(
        (static_cast<int64_t>(value_) * rhs.value_) >> kFractionalBits));
  }
  constexpr FixedPoint operator/(const FixedPoint& rhs) const {
    return FromRaw(static_cast<int32_t>(
        (static_cast<int64_t>(value_) << kFractionalBits) / rhs.value_));
  }

  // ===== 复合赋值 =====

  constexpr FixedPoint& operator+=(const FixedPoint& rhs) {
    value_ += rhs.value_;
    return *this;
  }
  constexpr FixedPoint& operator-=(const FixedPoint& rhs) {
    value_ -= rhs.value_;
    return *this;
  }
  constexpr FixedPoint& operator*=(const FixedPoint& rhs) {
    *this = *this * rhs;
    return *this;
  }
  constexpr FixedPoint& operator/=(const FixedPoint& rhs) {
    *this = *this / rhs;
    return *this;
  }

  // ===== 比较运算 =====

  constexpr bool operator==(const FixedPoint& rhs) const {
    return value_ == rhs.value_;
  }
  constexpr bool operator!=(const FixedPoint& rhs) const {
    return value_ != rhs.value_;
  }
  constexpr bool operator<(const FixedPoint& rhs) const {
    return value_ < rhs.value_;
  }
  constexpr bool operator<=(const FixedPoint& rhs) const {
    return value_ <= rhs.value_;
  }
  constexpr bool operator>(const FixedPoint& rhs) const {
    return value_ > rhs.value_;
  }
  constexpr bool operator>=(const FixedPoint& rhs) const {
    return value_ >= rhs.value_;
  }

  // ===== 一元运算 =====

  constexpr FixedPoint operator-() const { return FromRaw(-value_); }
  constexpr FixedPoint Abs() const {
    return FromRaw(value_ < 0 ? -value_ : value_);
  }
  constexpr FixedPoint operator%(const FixedPoint& rhs) const {
    return FromRaw(value_ % rhs.value_);
  }

  // ===== 三角函数（CORDIC 算法，纯整数） =====

  /// 纯整数 CORDIC sin — 16 次迭代，后处理除以 K
  static FixedPoint Sin(FixedPoint angle);

  /// 纯整数 CORDIC cos — 16 次迭代，后处理除以 K
  static FixedPoint Cos(FixedPoint angle);

  /// 整数 Newton 法 sqrt — 无浮点依赖
  static FixedPoint Sqrt(FixedPoint x);

  /// 纯整数 atan2 — 用于向量角度计算
  static FixedPoint Atan2(FixedPoint y, FixedPoint x);

  // ===== 常量 =====

  static constexpr FixedPoint Zero() { return FixedPoint(); }
  static constexpr FixedPoint One() { return FixedPoint(1); }
  static constexpr FixedPoint Half() {
    return FromRaw(1 << (kFractionalBits - 1));
  }
  static constexpr FixedPoint Pi() { return FromRaw(205887); }
  static constexpr FixedPoint TwoPi() { return FromRaw(411774); }
  static constexpr FixedPoint HalfPi() { return FromRaw(102943); }
  static constexpr FixedPoint NegHalfPi() { return FromRaw(-102943); }

 private:
  static constexpr int kFractionalBits = 16;
  static constexpr int32_t kFractionalMask = (1 << kFractionalBits) - 1;
  static constexpr int32_t kOneRaw = 1 << kFractionalBits;

  int32_t value_;
};

// kOneRaw 暴露给 CORDIC 等非成员函数
static constexpr int32_t kFixedPointOneRaw = 1 << 16;

// ===================================================================
// CORDIC 实现
// ===================================================================
//
// CORDIC (COordinate Rotation DIgital Computer) 通过移位和加减法
// 逼近 sin/cos 值。
//
// 算法流程：
//   1. 从 (1, 0) 开始
//   2. 对于 i = 0..15，根据残差角度的符号旋转
//   3. 最终得到 (K·cos(a), K·sin(a))，其中 K ≈ 0.60725
//   4. 除以 K 得到 (cos(a), sin(a))
//
// 精度：16 次迭代 ≈ 16 位有效数字，误差 < 0.001

// atan(2^(-i)) * 65536，i = 0..15
// atan(2^(-i)) * 65536，精确 Q16.16 值
inline constexpr int32_t kCordicAtanTable[16] = {
    51472,  // atan(1.0)     * 65536 = 51471.9
    30386,  // atan(0.5)     * 65536 = 30385.6
    16055,  // atan(0.25)    * 65536 = 16054.9
     8150,  // atan(0.125)   * 65536 =  8149.7
     4091,  // atan(0.0625)  * 65536 =  4090.7
     2047,  // atan(0.03125) * 65536 =  2047.3
     1024,  // atan(0.015625)* 65536 =  1023.9
      512,  // atan(2^-7)    * 65536 =   512.0
      256,  // atan(2^-8)    * 65536 =   256.0
      128,  // atan(2^-9)    * 65536 =   128.0
       64,  // atan(2^-10)   * 65536 =    64.0
       32,  // atan(2^-11)   * 65536 =    32.0
       16,  // atan(2^-12)   * 65536 =    16.0
        8,  // atan(2^-13)   * 65536 =     8.0
        4,  // atan(2^-14)   * 65536 =     4.0
        2   // atan(2^-15)   * 65536 =     2.0
};

// K = ∏cos(atan(2^(-i))) ≈ 0.607252935
// K * 65536 ≈ 39796
inline constexpr int32_t kCordicGain = 39796;

// 1/K * 2^32 ≈ 7063833311 (Q32 格式，用于后处理)
inline constexpr int64_t kCordicInverseGainQ32 = 7063833311LL;

// CORDIC 内联辅助：执行 16 次迭代
// 输入：角度 a（Q16.16），输出：(x=COS·K, y=SIN·K)
inline void CordicRotate(int32_t a, int32_t& out_x, int32_t& out_y) {
  // CORDIC 旋转模式：从 (K, 0) 开始旋转到角度 a
  // 此方向产生 (cos/K, sin/K) 的缩放输出
  // 初始值设为 K 使得最终输出已经是 (cos, sin)，无需后处理
  int32_t x = kCordicGain;  // K * 65536 ≈ 39796
  int32_t y = 0;

  for (int i = 0; i < 16; ++i) {
    if (a >= 0) {
      int32_t x_new = x - (y >> i);
      int32_t y_new = y + (x >> i);
      x = x_new;
      y = y_new;
      a -= kCordicAtanTable[i];
    } else {
      int32_t x_new = x + (y >> i);
      int32_t y_new = y - (x >> i);
      x = x_new;
      y = y_new;
      a += kCordicAtanTable[i];
    }
  }

  out_x = x;
  out_y = y;
}

inline FixedPoint FixedPoint::Sin(FixedPoint angle) {
  // 角度归一化到 [-π, π]
  int32_t a = angle.ToRaw();
  const int32_t pi_raw = Pi().ToRaw();
  const int32_t two_pi_raw = TwoPi().ToRaw();

  if (a > two_pi_raw) a -= two_pi_raw;
  if (a < -two_pi_raw) a += two_pi_raw;
  if (a > pi_raw) a -= two_pi_raw;
  if (a < -pi_raw) a += two_pi_raw;

  // CORDIC 旋转（初始值 K 使得输出无需后处理）
  int32_t x, y;
  CordicRotate(a, x, y);
  return FromRaw(y);
}

inline FixedPoint FixedPoint::Cos(FixedPoint angle) {
  // 角度归一化到 [-π, π]
  int32_t a = angle.ToRaw();
  const int32_t pi_raw = Pi().ToRaw();
  const int32_t two_pi_raw = TwoPi().ToRaw();
  const int32_t half_pi_raw = HalfPi().ToRaw();

  if (a > two_pi_raw) a -= two_pi_raw;
  if (a < -two_pi_raw) a += two_pi_raw;
  if (a > pi_raw) a -= two_pi_raw;
  if (a < -pi_raw) a += two_pi_raw;

  // CORDIC 收敛范围约 ±π/2，超出部分用 cos(a) = -cos(a ∓ π)
  bool negate = false;
  if (a > half_pi_raw) {
    a -= pi_raw;
    negate = true;
  } else if (a < -half_pi_raw) {
    a += pi_raw;
    negate = true;
  }

  // CORDIC 旋转（初始值 K 使得输出无需后处理）
  int32_t x, y;
  CordicRotate(a, x, y);
  return negate ? FromRaw(-x) : FromRaw(x);
}

inline FixedPoint FixedPoint::Sqrt(FixedPoint x) {
  if (x < Zero()) return Zero();
  if (x == Zero()) return Zero();

  // 整数 Newton 法求 sqrt
  // 对 raw 值左移 16 位后开方，保持 Q16.16 精度
  int64_t raw = static_cast<int64_t>(x.ToRaw()) << kFractionalBits;
  if (raw == 0) return Zero();

  int64_t result = raw;
  int64_t result_next = (result + 1) / 2;

  for (int i = 0; i < 64 && result_next < result; ++i) {
    result = result_next;
    result_next = (result + raw / result) / 2;
  }

  return FromRaw(static_cast<int32_t>(result));
}

inline FixedPoint FixedPoint::Atan2(FixedPoint y, FixedPoint x) {
  int32_t x_raw = x.ToRaw();
  int32_t y_raw = y.ToRaw();

  if (x_raw == 0 && y_raw == 0) return Zero();
  if (x_raw == 0) return y_raw > 0 ? HalfPi() : NegHalfPi();

  // CORDIC 向量模式
  int32_t angle = 0;
  int32_t abs_x = x_raw > 0 ? x_raw : -x_raw;
  int32_t abs_y = y_raw > 0 ? y_raw : -y_raw;

  bool swapped = false;
  if (abs_y > abs_x) {
    int32_t tmp = abs_x;
    abs_x = abs_y;
    abs_y = tmp;
    swapped = true;
  }

  int32_t xi = abs_x;
  int32_t yi = abs_y;

  for (int i = 0; i < 16; ++i) {
    if (yi >= 0) {
      // yi > 0: 顺时针旋转（减小 yi）
      int32_t xi_new = xi + (yi >> i);
      int32_t yi_new = yi - (xi >> i);
      xi = xi_new;
      yi = yi_new;
      angle -= kCordicAtanTable[i];
    } else {
      // yi < 0: 逆时针旋转（增大 yi）
      int32_t xi_new = xi - (yi >> i);
      int32_t yi_new = yi + (xi >> i);
      xi = xi_new;
      yi = yi_new;
      angle += kCordicAtanTable[i];
    }
  }

  if (swapped) {
    angle = HalfPi().ToRaw() - angle;
  }

  if (x_raw < 0) {
    if (y_raw >= 0) {
      angle = Pi().ToRaw() - angle;
    } else {
      angle = -Pi().ToRaw() - angle;
    }
  } else {
    if (y_raw < 0) {
      angle = -angle;
    }
  }

  return FromRaw(angle);
}

}  // namespace blunted

#endif
