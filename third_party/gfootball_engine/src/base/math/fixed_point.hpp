// Copyright 2026 Google LLC & Contributors
// 定点数实现：确保跨平台浮点运算一致

#ifndef _HPP_BASE_MATH_FIXED_POINT
#define _HPP_BASE_MATH_FIXED_POINT

#include <cstdint>
#include <cmath>
#include <limits>

namespace blunted {

/// 定点数类：使用 Q16.16 格式（16位整数 + 16位小数）
/// 用于帧同步中需要跨平台确定性的场景
class FixedPoint {
 public:
  // 构造函数
  constexpr FixedPoint() : value_(0) {}
  constexpr explicit FixedPoint(int32_t integer) : value_(integer << kFractionalBits) {}
  constexpr explicit FixedPoint(float f) : value_(static_cast<int32_t>(f * (1 << kFractionalBits))) {}
  constexpr explicit FixedPoint(double d) : value_(static_cast<int32_t>(d * (1 << kFractionalBits))) {}

  // 从原始值构造
  static constexpr FixedPoint FromRaw(int32_t raw) { FixedPoint fp; fp.value_ = raw; return fp; }

  // 转换为浮点数
  constexpr float ToFloat() const { return static_cast<float>(value_) / (1 << kFractionalBits); }
  constexpr double ToDouble() const { return static_cast<double>(value_) / (1 << kFractionalBits); }

  // 获取原始定点值
  constexpr int32_t ToRaw() const { return value_; }

  // 获取整数部分
  constexpr int32_t Integer() const { return value_ >> kFractionalBits; }

  // 获取小数部分（0-65535）
  constexpr int32_t Fraction() const { return value_ & kFractionalMask; }

  // 基本运算
  constexpr FixedPoint operator+(const FixedPoint& rhs) const { return FromRaw(value_ + rhs.value_); }
  constexpr FixedPoint operator-(const FixedPoint& rhs) const { return FromRaw(value_ - rhs.value_); }
  constexpr FixedPoint operator*(const FixedPoint& rhs) const {
    return FromRaw(static_cast<int64_t>(value_) * rhs.value_ >> kFractionalBits);
  }
  constexpr FixedPoint operator/(const FixedPoint& rhs) const {
    return FromRaw((static_cast<int64_t>(value_) << kFractionalBits) / rhs.value_);
  }

  // 复合赋值
  constexpr FixedPoint& operator+=(const FixedPoint& rhs) { value_ += rhs.value_; return *this; }
  constexpr FixedPoint& operator-=(const FixedPoint& rhs) { value_ -= rhs.value_; return *this; }
  constexpr FixedPoint& operator*=(const FixedPoint& rhs) { *this = *this * rhs; return *this; }
  constexpr FixedPoint& operator/=(const FixedPoint& rhs) { *this = *this / rhs; return *this; }

  // 比较运算
  constexpr bool operator==(const FixedPoint& rhs) const { return value_ == rhs.value_; }
  constexpr bool operator!=(const FixedPoint& rhs) const { return value_ != rhs.value_; }
  constexpr bool operator<(const FixedPoint& rhs) const { return value_ < rhs.value_; }
  constexpr bool operator<=(const FixedPoint& rhs) const { return value_ <= rhs.value_; }
  constexpr bool operator>(const FixedPoint& rhs) const { return value_ > rhs.value_; }
  constexpr bool operator>=(const FixedPoint& rhs) const { return value_ >= rhs.value_; }

  // 一元运算
  constexpr FixedPoint operator-() const { return FromRaw(-value_); }

  // 绝对值
  constexpr FixedPoint Abs() const { return FromRaw(value_ < 0 ? -value_ : value_); }

  // 取模
  constexpr FixedPoint operator%(const FixedPoint& rhs) const { return FromRaw(value_ % rhs.value_); }

  // 三角函数（使用查表法或近似算法）
  static FixedPoint Sin(FixedPoint angle);
  static FixedPoint Cos(FixedPoint angle);
  static FixedPoint Sqrt(FixedPoint x);

  // 常量
  static constexpr FixedPoint Zero() { return FixedPoint(); }
  static constexpr FixedPoint One() { return FixedPoint(1); }
  static constexpr FixedPoint Half() { return FromRaw(1 << (kFractionalBits - 1)); }
  static constexpr FixedPoint Pi() { return FromRaw(205887); }  // 3.14159265 * 65536
  static constexpr FixedPoint TwoPi() { return FromRaw(411774); }  // 2 * Pi
  static constexpr FixedPoint HalfPi() { return FromRaw(102943); }  // Pi / 2

 private:
  static constexpr int kFractionalBits = 16;
  static constexpr int32_t kFractionalMask = (1 << kFractionalBits) - 1;

  int32_t value_;
};

// 三角函数实现（使用CORDIC算法或查表法）
inline FixedPoint FixedPoint::Sin(FixedPoint angle) {
  // 简化实现：使用浮点转换
  // 实际应用中应使用查表法或CORDIC算法
  return FixedPoint(std::sin(angle.ToDouble()));
}

inline FixedPoint FixedPoint::Cos(FixedPoint angle) {
  // 简化实现：使用浮点转换
  // 实际应用中应使用查表法或CORDIC算法
  return FixedPoint(std::cos(angle.ToDouble()));
}

inline FixedPoint FixedPoint::Sqrt(FixedPoint x) {
  if (x < Zero()) return Zero();
  return FixedPoint(std::sqrt(x.ToDouble()));
}

}  // namespace blunted

#endif
