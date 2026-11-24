package nativeworker

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"pokemonbattleinference/server/internal/jobs"
	"pokemonbattleinference/server/internal/workerprocess"
	"strings"
	"sync"
	"time"
)

// Options 明确调度身份、冻结 revision、子进程版本和租约时序，不读取隐藏生产配置。
type Options struct {
	Owner             string
	Revision          string
	EngineVersion     string
	Executable        string
	LeaseDuration     time.Duration
	HeartbeatInterval time.Duration
	PollInterval      time.Duration
	DatabaseTimeout   time.Duration
}

// Worker 使用真实 Store 顺序维护租约，在至多 ProcessCount 个独立进程中执行冻结请求。
// 各 RunOnce 调用不得并行使用同一实例；构造本身不连接或迁移数据库。
type Worker struct {
	store   *jobs.Store
	options Options
}

// New 验证 store/options 后返回独立调度器；缺失可执行文件或不安全时序直接失败，不领取任何任务。
func New(store *jobs.Store, options Options) (*Worker, error) {
	if store == nil || strings.TrimSpace(options.Owner) == "" || strings.TrimSpace(options.Revision) == "" || options.EngineVersion == "" {
		return nil, errors.New("store, owner, revision and engine version are required")
	}
	if !filepath.IsAbs(options.Executable) {
		return nil, errors.New("worker executable must be absolute")
	}
	info, err := os.Stat(options.Executable)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Mode()&0111 == 0 {
		return nil, errors.New("worker path must be executable")
	}
	if options.PollInterval <= 0 || options.HeartbeatInterval < options.PollInterval ||
		options.HeartbeatInterval > options.LeaseDuration/3 || options.DatabaseTimeout <= 0 || options.DatabaseTimeout >= options.LeaseDuration/2 {
		return nil, errors.New("invalid lease, heartbeat, polling or database timeout")
	}
	return &Worker{store: store, options: options}, nil
}

// Serve 持续领取兼容 revision 的任务；ctx 取消会回收本进程的全部原生子进程并保留未确认租约供恢复。
// 任一数据库/租约错误返回给监督者，绝不在失去 owner 后继续提交结果。
func (worker *Worker) Serve(ctx context.Context) error {
	for {
		worked, err := worker.RunOnce(ctx)
		if err != nil {
			return err
		}
		if worked {
			continue
		}
		timer := time.NewTimer(worker.options.PollInterval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}

// RunOnce 原子领取并完成最多一个持久化任务；空队列返回 false，错误不会自动把任务标成成功。
// 父 ctx 关闭表示 daemon 停机，尚未确认 case 留待租约过期恢复；用户取消则保存明确 cancelled 终态。
func (worker *Worker) RunOnce(ctx context.Context) (bool, error) {
	query, cancel := context.WithTimeout(ctx, worker.options.DatabaseTimeout)
	job, err := worker.store.ClaimJob(query, worker.options.Owner, worker.options.Revision, time.Now().UTC(), worker.options.LeaseDuration)
	cancel()
	if err != nil || job == nil {
		return false, err
	}
	query, cancel = context.WithTimeout(ctx, worker.options.DatabaseTimeout)
	definition, err := worker.store.Definition(query, job.ID)
	cancel()
	if err != nil {
		return true, err
	}
	if err = definition.Validate(); err != nil {
		return true, err
	}
	if definition.ID != job.ID || definition.Revision != job.Revision || len(definition.Cases) != job.Counts.Total {
		return true, errors.New("persisted job and frozen definition disagree")
	}
	return true, worker.runJob(ctx, job.ID, definition)
}

// completion 是一个已退出原生子进程的独占反馈；数据库写入只由 coordinator 的主循环执行。
type completion struct {
	pair   string
	result jobs.Result
}

// runJob 为 id 调度 definition 的真实冻结请求；有界结果 channel 与 WaitGroup 确保退出时没有遗留子进程。
func (worker *Worker) runJob(ctx context.Context, id string, definition jobs.Definition) error {
	children, stop := context.WithCancel(ctx)
	var waiting sync.WaitGroup
	active := make(map[string]context.CancelFunc)
	results := make(chan completion, definition.Spec.ProcessCount)
	defer func() {
		stop()
		for _, cancel := range active {
			cancel()
		}
		waiting.Wait()
	}()
	inputs := make(map[string][]byte, len(definition.Cases))
	for _, item := range definition.Cases {
		inputs[item.PairID] = item.CoreRequest
	}
	heartbeat := time.Now().UTC()
	ticker := time.NewTicker(worker.options.PollInterval)
	defer ticker.Stop()
	for {
		query, cancel := context.WithTimeout(ctx, worker.options.DatabaseTimeout)
		current, err := worker.store.Get(query, id)
		if err != nil {
			cancel()
			return err
		}
		if current.Status == jobs.Succeeded || current.Status == jobs.CompletedWithFailures || current.Status == jobs.Cancelled || current.Status == jobs.Failed {
			cancel()
			return nil
		}
		now := time.Now().UTC()
		// 先确认 coordinator 身份，失去租约立即取消全部计算，不等下一次续租时才发现。
		if current.Lease == nil || current.Lease.Owner != worker.options.Owner || !current.Lease.ExpiresAt.After(now) {
			cancel()
			return jobs.ErrLeaseConflict
		}
		if now.Sub(heartbeat) >= worker.options.HeartbeatInterval {
			err = worker.store.HeartbeatJob(query, id, worker.options.Owner, now, worker.options.LeaseDuration)
			if err == nil && len(active) > 0 {
				pairs := make([]string, 0, len(active))
				for pair := range active {
					pairs = append(pairs, pair)
				}
				err = worker.store.HeartbeatCases(query, id, worker.options.Owner, pairs, now, worker.options.LeaseDuration)
			}
			if err != nil {
				cancel()
				return err
			}
			heartbeat = now
		}
		if current.Status == jobs.CancelRequested {
			// 仅用户请求取消会写 cancelled；父进程停机保留 lease，由下个 daemon 恢复。
			for _, cancelChild := range active {
				cancelChild()
			}
			if _, err = worker.store.CancelUnclaimed(query, id, now); err != nil {
				cancel()
				return err
			}
		} else if capacity := definition.Spec.ProcessCount - len(active); capacity > 0 {
			cases, claimErr := worker.store.ClaimCases(query, id, worker.options.Owner, definition.Revision, now, worker.options.LeaseDuration, capacity)
			// GET 与领取之间可能刚好收到取消，重读状态进入取消路径，不把合法竞态当作 daemon 崩溃。
			if errors.Is(claimErr, jobs.ErrTransition) {
				cancel()
				continue
			}
			if claimErr != nil {
				cancel()
				return claimErr
			}
			for _, item := range cases {
				request, exists := inputs[item.Definition.PairID]
				if !exists {
					cancel()
					return errors.New("claimed case has no frozen input")
				}
				if _, err = worker.store.RecordProgress(query, id, item.Definition.PairID, worker.options.Owner, definition.Revision, now,
					jobs.Progress{Phase: "executing-core"}); err != nil {
					cancel()
					return err
				}
				child, cancelChild := context.WithCancel(children)
				pair := item.Definition.PairID
				active[pair] = cancelChild
				waiting.Add(1)
				// request 只读借用持久化副本；完成消息缓冲足够容纳本轮所有子进程，关闭时也不会阻塞发送。
				go func() { defer waiting.Done(); results <- completion{pair, worker.execute(child, request)} }()
			}
		}
		current, err = worker.store.Get(query, id)
		if err == nil && current.Counts.Pending == 0 && current.Counts.Running == 0 {
			_, err = worker.store.Finalize(query, id, now)
			cancel()
			return err
		}
		cancel()
		if err != nil {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case result := <-results:
			if ctx.Err() != nil {
				return ctx.Err()
			}
			cancelChild, exists := active[result.pair]
			if !exists {
				return errors.New("native process completed without active lease")
			}
			query, cancel = context.WithTimeout(ctx, worker.options.DatabaseTimeout)
			_, err = worker.store.RecordResult(query, id, result.pair, worker.options.Owner, definition.Revision, time.Now().UTC(), result.result)
			cancel()
			cancelChild()
			delete(active, result.pair)
			if err != nil {
				return err
			}
		case <-ticker.C:
		}
	}
}

// execute 将 request 原样交给绝对路径原生进程，返回可持久化终态；只转换传输错误，不实现求解规则。
// ctx 的取消由 coordinator 的用户请求或关闭触发；关闭路径不会调用 RecordResult。
func (worker *Worker) execute(ctx context.Context, request []byte) jobs.Result {
	input, err := readGraph(request)
	if err != nil {
		return failure(jobs.Failed, "invalid_configuration", "frozen input is not a supported graph request")
	}
	response, err := workerprocess.Execute(ctx, worker.options.Executable, request)
	if err != nil {
		if ctx.Err() != nil {
			return failure(jobs.Cancelled, "cancelled", "job cancellation stopped native process")
		}
		var native *workerprocess.Failure
		if errors.As(err, &native) {
			switch native.Code {
			case "unsupported":
				return failure(jobs.Failed, "unsupported_mechanism", "native operation is unsupported")
			case "invalid_input":
				return failure(jobs.Failed, "invalid_configuration", "native input is invalid")
			case "resource_limit":
				return failure(jobs.Truncated, "solver_unresolved", "native computation exceeded a resource budget")
			}
		}
		return failure(jobs.Failed, "worker_crash", "native process did not return a valid result")
	}
	result, err := decodeResult(input, response, worker.options.EngineVersion)
	if errors.Is(err, errNativeVersion) {
		return failure(jobs.Failed, "calculation_revision_mismatch", "native engine version does not match coordinator")
	}
	if err != nil {
		return failure(jobs.Failed, "worker_crash", "native result violates the result contract")
	}
	return result
}
