#include "pbi/cancellation.hpp"
#include <gtest/gtest.h>
#include <chrono>
#include <future>
#include <thread>
#include <vector>

namespace pbi {
/// 空令牌不分配状态且永不取消；请求只能将同源状态由 false 改为 true 一次。
TEST(Cancellation, EmptyTokenAndMonotonicRequest) {
  const CancellationToken empty;
  EXPECT_FALSE(empty.Requested());
  const CancellationSource source;
  const auto token = source.Token();
  const auto copied_token = token;
  const auto copied_source = source;
  EXPECT_FALSE(token.Requested()); EXPECT_FALSE(copied_source.Requested());
  EXPECT_TRUE(source.Request()); EXPECT_FALSE(copied_source.Request()); EXPECT_FALSE(source.Request());
  EXPECT_TRUE(token.Requested()); EXPECT_TRUE(copied_token.Requested()); EXPECT_TRUE(copied_source.Requested());
  EXPECT_FALSE(empty.Requested());
}

/// 令牌/源共享状态的拥有权；源销毁或令牌副本移动不会留下悬空取消状态。
TEST(Cancellation, SharedLifetimeAfterSourceDestructionAndMoves) {
  const auto requested_after_source_destroyed = [] {
    const CancellationSource source;
    auto token = source.Token(); source.Request();
    return token;
  }();
  EXPECT_TRUE(requested_after_source_destroyed.Requested());
  CancellationSource survivor;
  CancellationToken retained;
  {
    const CancellationSource original;
    survivor = original; retained = original.Token();
  }
  EXPECT_FALSE(retained.Requested()); EXPECT_TRUE(survivor.Request()); EXPECT_TRUE(retained.Requested());
  auto token = survivor.Token(); const auto moved = std::move(token);
  EXPECT_FALSE(token.Requested()); EXPECT_TRUE(moved.Requested());
  auto source = std::move(survivor);
  EXPECT_FALSE(survivor.Requested()); EXPECT_FALSE(survivor.Token().Requested()); EXPECT_FALSE(survivor.Request());
  EXPECT_TRUE(source.Requested()); EXPECT_TRUE(source.Token().Requested());
}

/// 多线程读同源副本并同时请求取消，只有一个请求者首次改变状态；没有回调或平台等待原语。
TEST(Cancellation, ConcurrentReadersAndRequesters) {
  const CancellationSource source;
  const auto token = source.Token();
  std::atomic<std::size_t> first_requests{0}, observed{0};
  std::promise<void> release;
  const auto start = release.get_future().share();
  std::vector<std::thread> threads;
  for (std::size_t index = 0; index < 16; ++index) threads.emplace_back([token, start, &observed] {
    start.wait();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds{2};
    while (!token.Requested() && std::chrono::steady_clock::now() < deadline) std::this_thread::yield();
    if (token.Requested()) observed.fetch_add(1, std::memory_order_relaxed);
  });
  for (std::size_t index = 0; index < 8; ++index) threads.emplace_back([source, start, &first_requests] {
    start.wait(); if (source.Request()) first_requests.fetch_add(1, std::memory_order_relaxed);
  });
  release.set_value();
  for (auto& thread : threads) thread.join();
  EXPECT_EQ(first_requests.load(), 1); EXPECT_EQ(observed.load(), 16); EXPECT_TRUE(source.Requested());
}
} // namespace pbi
