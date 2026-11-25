#pragma once

#include <atomic>
#include <memory>
#include <utility>

namespace pbi {
class CancellationSource;
/// 可复制的只读协作取消令牌；空令牌永不取消，持有状态直到最后一个源/令牌释放。
/// 不注册回调、不创建线程，也不依赖某个平台尚未实现的 C++20 stop_token。
class CancellationToken {
public:
  /// 无参数；构造不分配内存的空令牌，Requested 恒为 false。
  CancellationToken() noexcept = default;
  /// @param other 只读令牌；共享相同取消状态，不复制或重置取消标志。
  CancellationToken(const CancellationToken& other) noexcept = default;
  /// @param other 转移共享状态，移动后的 other 为空且永不取消。
  CancellationToken(CancellationToken&& other) noexcept = default;
  /// @param other 只读令牌；@return 赋值后的自身，同源副本观察同一个原子标志。
  CancellationToken& operator=(const CancellationToken& other) noexcept = default;
  /// @param other 转移共享状态；@return 赋值后的自身，other 变为空令牌。
  CancellationToken& operator=(CancellationToken&& other) noexcept = default;
  /// @return 当前是否已请求取消；线程安全 acquire 读取，不修改状态或保留外部裸指针。
  [[nodiscard]] bool Requested() const noexcept { return state_ && state_->load(std::memory_order_acquire); }
private:
  friend class CancellationSource;
  /// @param state 转移拥有共享引用的只读原子状态，可为空；仅取消源可以创建关联令牌。
  explicit CancellationToken(std::shared_ptr<const std::atomic<bool>> state) noexcept : state_(std::move(state)) {}
  std::shared_ptr<const std::atomic<bool>> state_;
};

/// 单向原子取消源；复制的源和令牌共享生命周期，取消不能被撤销。
/// 多线程可以同时 Request/Requested/Token；同一对象的赋值/移动/销毁仍由调用方同步。
class CancellationSource {
public:
  /// 无参数；分配独立未取消状态，分配失败允许抛 bad_alloc，由 C ABI 创建入口隔离。
  CancellationSource() : state_(std::make_shared<std::atomic<bool>>(false)) {}
  /// @param other 只读源；共享其取消状态，不创建第二套标志。
  CancellationSource(const CancellationSource& other) noexcept = default;
  /// @param other 转移共享状态；移动后的源为空，查询/请求仍安全。
  CancellationSource(CancellationSource&& other) noexcept = default;
  /// @param other 只读源；@return 自身，原状态仍由其已有令牌安全持有。
  CancellationSource& operator=(const CancellationSource& other) noexcept = default;
  /// @param other 转移共享状态；@return 自身，other 变为空源。
  CancellationSource& operator=(CancellationSource&& other) noexcept = default;
  /// @return 拥有共享状态引用的只读令牌，源销毁后仍有效；空源返回空令牌。
  [[nodiscard]] CancellationToken Token() const noexcept { return CancellationToken{state_}; }
  /// @return 是否由本调用首次把状态从未取消改为取消；空源或重复请求返回 false。
  bool Request() const noexcept { return state_ && !state_->exchange(true, std::memory_order_acq_rel); }
  /// @return 是否已请求取消；与全部同源令牌观察同一单向原子标志。
  [[nodiscard]] bool Requested() const noexcept { return state_ && state_->load(std::memory_order_acquire); }
private:
  std::shared_ptr<std::atomic<bool>> state_;
};
} // namespace pbi
