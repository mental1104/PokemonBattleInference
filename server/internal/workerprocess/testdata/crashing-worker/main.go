// crashing-worker 只用于独立进程验收，真实 CGO SIGSEGV 不能终止测试父进程。
package main

/*
#include <signal.h>

// trigger_native_crash 只终止当前测试子进程，用于核验 Go runtime exit=2 的分类。
static void trigger_native_crash(void) { raise(SIGSEGV); }
*/
import "C"

// main 进入真实 C 调用触发 SIGSEGV，不包含网络、数据读写或可配置注入入口。
func main() { C.trigger_native_crash() }
