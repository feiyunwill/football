#!/bin/bash
# 自动代码审查脚本 - 专业实现
# 用法: ./auto_review.sh <task_id|plan_id|milestone_id> [review_type]

set -e

TARGET_ID=$1
REVIEW_TYPE=${2:-"all"}

if [ -z "$TARGET_ID" ]; then
  echo "用法: $0 <task_id|plan_id|milestone_id> [review_type]"
  echo "  review_type: style, security, performance, all"
  echo "示例: $0 task-1.1.1.1 style"
  exit 1
fi

echo "=== 自动代码审查: $TARGET_ID ==="
echo "审查类型: $REVIEW_TYPE"

# 审查报告目录
REPORT_DIR=".project/reports"
mkdir -p "$REPORT_DIR"
REPORT_FILE="${REPORT_DIR}/review-$(date +%Y%m%d-%H%M%S).md"

# 初始化报告
cat > "$REPORT_FILE" << EOF
# 代码审查报告: $TARGET_ID

- **时间**: $(date)
- **审查类型**: $REVIEW_TYPE

## 审查结果

EOF

# 1. 确定审查范围
echo "1. 确定审查范围..."
if [[ "$TARGET_ID" == task-* ]]; then
  echo "   范围: 代码风格 + 安全性"
  REVIEW_SCOPE="basic"
elif [[ "$TARGET_ID" == plan-* ]]; then
  echo "   范围: 代码风格 + 安全性 + 性能"
  REVIEW_SCOPE="standard"
elif [[ "$TARGET_ID" == ms-* ]]; then
  echo "   范围: 全面审查"
  REVIEW_SCOPE="comprehensive"
else
  echo "   错误: 未知的 ID 格式"
  exit 1
fi

# 2. 代码风格检查 (clang-format)
run_style_check() {
  echo "2. 代码风格检查 (clang-format)..."
  
  if command -v clang-format &> /dev/null; then
    # 获取最近修改的 C++ 文件
    CHANGED_FILES=$(git diff --name-only HEAD~1 2>/dev/null | grep -E "\.(cpp|hpp|h)$" | head -10)
    
    if [ -n "$CHANGED_FILES" ]; then
      STYLE_ERRORS=0
      for file in $CHANGED_FILES; do
        if [ -f "$file" ]; then
          # 检查格式差异
          if ! clang-format --dry-run -style=file "$file" 2>/dev/null | grep -q "code should be"; then
            echo "   ✅ $file: 格式正确"
          else
            echo "   ⚠️  $file: 需要格式化"
            ((STYLE_ERRORS++))
          fi
        fi
      done
      
      if [ $STYLE_ERRORS -eq 0 ]; then
        echo "   ✅ 代码风格检查通过"
        echo "- ✅ 代码风格检查 (clang-format): 通过" >> "$REPORT_FILE"
      else
        echo "   ⚠️  $STYLE_ERRORS 个文件需要格式化"
        echo "- ⚠️ 代码风格检查 (clang-format): $STYLE_ERRORS 个文件需要格式化" >> "$REPORT_FILE"
      fi
    else
      echo "   ⚠️  没有检测到 C++ 文件变更"
      echo "- ⚠️ 代码风格检查: 无 C++ 文件变更" >> "$REPORT_FILE"
    fi
  else
    echo "   ⚠️  clang-format 未安装"
    echo "- ⚠️ 代码风格检查: clang-format 未安装" >> "$REPORT_FILE"
  fi
  
  return 0
}

# 3. 静态分析 (clang-tidy)
run_static_analysis() {
  echo "3. 静态分析 (clang-tidy)..."
  
  if command -v clang-tidy &> /dev/null; then
    # 获取最近修改的 C++ 文件
    CHANGED_FILES=$(git diff --name-only HEAD~1 2>/dev/null | grep -E "\.(cpp|hpp|h)$" | head -5)
    
    if [ -n "$CHANGED_FILES" ]; then
      ISSUES_FOUND=0
      for file in $CHANGED_FILES; do
        if [ -f "$file" ]; then
          echo "   分析 $file..."
          
          # 运行 clang-tidy
          if clang-tidy "$file" -- -std=c++23 -I src 2>/dev/null | grep -q "warning:"; then
            echo "   ⚠️  $file: 发现问题"
            clang-tidy "$file" -- -std=c++23 -I src 2>/dev/null | grep "warning:" | head -5
            ((ISSUES_FOUND++))
          else
            echo "   ✅ $file: 无问题"
          fi
        fi
      done
      
      if [ $ISSUES_FOUND -eq 0 ]; then
        echo "   ✅ 静态分析通过"
        echo "- ✅ 静态分析 (clang-tidy): 通过" >> "$REPORT_FILE"
      else
        echo "   ⚠️  $ISSUES_FOUND 个文件有问题"
        echo "- ⚠️ 静态分析 (clang-tidy): $ISSUES_FOUND 个文件有问题" >> "$REPORT_FILE"
      fi
    else
      echo "   ⚠️  没有检测到 C++ 文件变更"
      echo "- ⚠️ 静态分析: 无 C++ 文件变更" >> "$REPORT_FILE"
    fi
  else
    echo "   ⚠️  clang-tidy 未安装"
    echo "- ⚠️ 静态分析: clang-tidy 未安装" >> "$REPORT_FILE"
  fi
  
  return 0
}

# 4. 安全性检查
run_security_check() {
  echo "4. 安全性检查..."
  
  SECURITY_ISSUES=0
  
  # 检查硬编码凭证
  if grep -r "password\|secret\|api_key\|token" --include="*.cpp" --include="*.hpp" --include="*.py" . 2>/dev/null | grep -v "test" | grep -v "example" | grep -v "TODO" | head -5; then
    echo "   ⚠️  发现可能的硬编码凭证"
    ((SECURITY_ISSUES++))
  fi
  
  # 检查危险函数
  if grep -r "system\|exec\|eval\|strcpy\|strcat" --include="*.cpp" --include="*.py" . 2>/dev/null | grep -v "test" | head -5; then
    echo "   ⚠️  发现可能的危险函数调用"
    ((SECURITY_ISSUES++))
  fi
  
  # 检查内存安全
  if grep -r "new\|delete\|malloc\|free" --include="*.cpp" . 2>/dev/null | grep -v "test" | head -5; then
    echo "   ⚠️  发现手动内存管理（建议使用智能指针）"
    ((SECURITY_ISSUES++))
  fi
  
  if [ $SECURITY_ISSUES -eq 0 ]; then
    echo "   ✅ 安全性检查通过"
    echo "- ✅ 安全性检查: 通过" >> "$REPORT_FILE"
  else
    echo "   ⚠️  发现 $SECURITY_ISSUES 个安全问题"
    echo "- ⚠️ 安全性检查: 发现 $SECURITY_ISSUES 个安全问题" >> "$REPORT_FILE"
  fi
  
  return 0
}

# 5. 性能检查
run_performance_check() {
  echo "5. 性能检查..."
  
  PERF_ISSUES=0
  
  # 检查嵌套循环
  NESTED_LOOPS=$(grep -r "for.*for" --include="*.cpp" . 2>/dev/null | grep -v "test" | wc -l)
  if [ $NESTED_LOOPS -gt 0 ]; then
    echo "   ⚠️  发现 $NESTED_LOOPS 个嵌套循环"
    ((PERF_ISSUES++))
  fi
  
  # 检查大量内存分配
  ALLOC_COUNT=$(grep -r "push_back\|emplace_back\|insert" --include="*.cpp" . 2>/dev/null | grep -v "test" | wc -l)
  if [ $ALLOC_COUNT -gt 100 ]; then
    echo "   ⚠️  发现大量容器操作 ($ALLOC_COUNT 次)"
    ((PERF_ISSUES++))
  fi
  
  # 检查虚函数调用
  VIRTUAL_CALLS=$(grep -r "virtual\|override" --include="*.cpp" --include="*.hpp" . 2>/dev/null | grep -v "test" | wc -l)
  if [ $VIRTUAL_CALLS -gt 50 ]; then
    echo "   ⚠️  发现大量虚函数调用 ($VIRTUAL_CALLS 次)"
    ((PERF_ISSUES++))
  fi
  
  if [ $PERF_ISSUES -eq 0 ]; then
    echo "   ✅ 性能检查通过"
    echo "- ✅ 性能检查: 通过" >> "$REPORT_FILE"
  else
    echo "   ⚠️  发现 $PERF_ISSUES 个性能问题"
    echo "- ⚠️ 性能检查: 发现 $PERF_ISSUES 个性能问题" >> "$REPORT_FILE"
  fi
  
  return 0
}

# 6. 依赖检查
run_dependency_check() {
  echo "6. 依赖检查..."
  
  # 检查头文件依赖
  INCLUDE_COUNT=$(grep -r "#include" --include="*.cpp" --include="*.hpp" . 2>/dev/null | grep -v "test" | wc -l)
  
  if [ $INCLUDE_COUNT -gt 500 ]; then
    echo "   ⚠️  发现大量头文件依赖 ($INCLUDE_COUNT 个)"
    echo "- ⚠️ 依赖检查: 大量头文件依赖" >> "$REPORT_FILE"
  else
    echo "   ✅ 依赖检查通过"
    echo "- ✅ 依赖检查: 通过" >> "$REPORT_FILE"
  fi
  
  return 0
}

# 执行审查
REVIEW_PASSED=0
REVIEW_FAILED=0

case "$REVIEW_SCOPE" in
  basic)
    run_style_check && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    run_security_check && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    ;;
  standard)
    run_style_check && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    run_static_analysis && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    run_security_check && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    run_performance_check && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    ;;
  comprehensive)
    run_style_check && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    run_static_analysis && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    run_security_check && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    run_performance_check && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    run_dependency_check && ((REVIEW_PASSED++)) || ((REVIEW_FAILED++))
    ;;
esac

# 7. 生成审查报告
echo "7. 生成审查报告..."
cat >> "$REPORT_FILE" << EOF

## 总结

- **通过**: $REVIEW_PASSED
- **失败**: $REVIEW_FAILED
- **时间**: $(date)

## 建议

1. 定期运行完整审查
2. 优先修复安全问题
3. 优化性能热点
4. 保持代码风格一致

EOF

echo "   审查报告已生成: $REPORT_FILE"

# 8. 返回结果
if [ $REVIEW_FAILED -gt 0 ]; then
  echo ""
  echo "=== 审查失败: $TARGET_ID ==="
  exit 1
else
  echo ""
  echo "=== 审查完成: $TARGET_ID ==="
  exit 0
fi
