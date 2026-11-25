package httpapi

import (
	"context"
	"database/sql"
	"errors"
	"math"
	"net/http"
	"pokemonbattleinference/server/internal/jobs"
	"strconv"
	"strings"
	"time"
)

// jobCounts 映射原通用任务面板的可靠状态桶。
type jobCounts struct {
	Total     int `json:"total"`
	Pending   int `json:"pending"`
	Running   int `json:"running"`
	Succeeded int `json:"succeeded"`
	Failed    int `json:"failed"`
	Truncated int `json:"truncated"`
	Cancelled int `json:"cancelled"`
	Completed int `json:"completed"`
}

// jobResource 仅表示实际资源预算，不代表算法求解完成百分比。
type jobResource struct {
	Used  int64 `json:"used"`
	Limit int64 `json:"limit"`
}

// runningCase 映射当前第一个 running case 的原始构图观测。
type runningCase struct {
	ConfigurationID      string    `json:"configuration_id"`
	Phase                string    `json:"phase"`
	Percent              float64   `json:"percent"`
	ObservedNodes        int64     `json:"observed_nodes"`
	ObservedEdges        int64     `json:"observed_edges"`
	NodeLimit            int       `json:"node_limit"`
	EdgeLimit            int       `json:"edge_limit"`
	ExpandedNodes        int64     `json:"expanded_nodes"`
	FrontierNodes        int64     `json:"frontier_nodes"`
	ActionPairsCompleted int64     `json:"action_pairs_completed"`
	ActionPairsTotal     int64     `json:"action_pairs_total"`
	UpdatedAt            time.Time `json:"updated_at"`
}

// jobProgress 保留原 DTO 的进度、资源和可空运行时长。
type jobProgress struct {
	Phase          string       `json:"phase"`
	Counts         jobCounts    `json:"counts"`
	StateNodes     jobResource  `json:"state_nodes"`
	StateEdges     jobResource  `json:"state_edges"`
	RunningCase    *runningCase `json:"running_case"`
	ElapsedSeconds *float64     `json:"elapsed_seconds"`
}

// jobLinks 是通用任务列表与取消动作的稳定 URL。
type jobLinks struct {
	Self   string `json:"self"`
	Cancel string `json:"cancel"`
}

// jobSummary 对应原 InferenceJobSummaryResponse，未包含完整图或 case 结果正文。
type jobSummary struct {
	JobID               string      `json:"job_id"`
	JobType             string      `json:"job_type"`
	Status              jobs.Status `json:"status"`
	Phase               string      `json:"phase"`
	RulesetID           string      `json:"ruleset_id"`
	VersionGroupID      int         `json:"version_group_id"`
	CalculationRevision string      `json:"calculation_revision"`
	CreatedAt           time.Time   `json:"created_at"`
	StartedAt           *time.Time  `json:"started_at"`
	UpdatedAt           time.Time   `json:"updated_at"`
	FinishedAt          *time.Time  `json:"finished_at"`
	CancelRequestedAt   *time.Time  `json:"cancel_requested_at"`
	CanCancel           bool        `json:"can_cancel"`
	Progress            jobProgress `json:"progress"`
	ErrorCode           *string     `json:"error_code"`
	ErrorMessage        *string     `json:"error_message"`
	Links               jobLinks    `json:"links"`
}

// jobPhase 只按已持久化状态生成原粗粒度阶段，不伪造动态计算进度。
func jobPhase(status jobs.Status) string {
	switch status {
	case jobs.Pending:
		return "queued"
	case jobs.Preparing:
		return "preparing_battle"
	case jobs.Running:
		return "solving_probabilities"
	case jobs.CancelRequested:
		return "cancel_requested"
	case jobs.Succeeded, jobs.CompletedWithFailures:
		return "completed"
	case jobs.Cancelled:
		return "cancelled"
	default:
		return "failed"
	}
}

// summary 合并 job 的冻结规格和首个真实运行 case；数据读取失败时不返回部分摘要。
func summary(ctx context.Context, store *jobs.Store, job jobs.Job) (jobSummary, error) {
	phase := jobPhase(job.Status)
	kind := "configuration-space"
	if strings.HasPrefix(job.ID, "fixed-one-on-one-job-") {
		kind = "fixed-one-on-one"
	}
	terminal := job.Status == jobs.Succeeded || job.Status == jobs.CompletedWithFailures || job.Status == jobs.Cancelled || job.Status == jobs.Failed
	c := job.Counts
	result := jobSummary{JobID: job.ID, JobType: kind, Status: job.Status, Phase: phase, RulesetID: job.RulesetID, VersionGroupID: job.VersionGroupID, CalculationRevision: job.Revision, CreatedAt: job.CreatedAt, StartedAt: job.StartedAt, UpdatedAt: job.UpdatedAt, FinishedAt: job.CompletedAt, CancelRequestedAt: job.CancelRequestedAt, CanCancel: !terminal, ErrorCode: job.FailureCode, ErrorMessage: job.Diagnostic, Links: jobLinks{"/v1/inference/jobs/" + job.ID, "/v1/inference/jobs/" + job.ID + "/cancel"}, Progress: jobProgress{Phase: phase, Counts: jobCounts{c.Total, c.Pending, c.Running, c.Succeeded, c.Failed, c.Truncated, c.Cancelled, c.Succeeded + c.Failed + c.Truncated + c.Cancelled}, StateNodes: jobResource{c.Nodes, int64(c.Total) * int64(job.Spec.MaxNodes)}, StateEdges: jobResource{c.Edges, int64(c.Total) * int64(job.Spec.MaxEdges)}}}
	if job.StartedAt != nil {
		end := job.UpdatedAt
		if job.CompletedAt != nil {
			end = *job.CompletedAt
		}
		elapsed := math.Max(0, end.Sub(*job.StartedAt).Seconds())
		result.Progress.ElapsedSeconds = &elapsed
	}
	if c.Running > 0 {
		cases, _, err := store.Cases(ctx, job.ID, []jobs.Status{jobs.Running}, 0, 1)
		if err != nil {
			return result, err
		}
		if len(cases) > 0 {
			item := cases[0]
			p := item.Progress
			phase := p.Phase
			if phase == "" {
				phase = "running"
			}
			ratio := math.Max(float64(p.ObservedNodes)/float64(job.Spec.MaxNodes), float64(p.ObservedEdges)/float64(job.Spec.MaxEdges))
			result.Progress.RunningCase = &runningCase{item.Definition.PairID, phase, math.Round(math.Min(100, ratio*100)*100) / 100, p.ObservedNodes, p.ObservedEdges, job.Spec.MaxNodes, job.Spec.MaxEdges, p.ExpandedNodes, p.Frontier, p.ActionPairsCompleted, p.ActionPairsTotal, item.UpdatedAt}
		}
	}
	return result, nil
}

// jobError 不泄漏 SQL 细节；对象缺失为 404，参数非法为 422，存储故障为 503。
func jobError(w http.ResponseWriter, err error) {
	if errors.Is(err, jobs.ErrNotFound) {
		detail(w, 404, "job not found")
		return
	}
	detail(w, 503, "job storage unavailable")
}

// registerJobs 迁移原通用任务列表、详情及幂等取消，支持读取已有 Python 任务快照。
// 此处不会自动启动 Worker；尚缺正式回合 Core 的创建 API 仍不受理任务。
func registerJobs(mux *http.ServeMux, db *sql.DB) {
	store := jobs.New(db)
	mux.HandleFunc("GET /v1/inference/jobs", func(w http.ResponseWriter, r *http.Request) {
		limit, ok := queryInt(w, r, "limit", 20, 1, 100)
		if !ok {
			return
		}
		offset, ok := queryInt(w, r, "cursor", 0, 0, 2147483647)
		if !ok {
			return
		}
		active := false
		var err error
		if value := r.URL.Query().Get("active_only"); value != "" {
			active, err = strconv.ParseBool(value)
			if err != nil {
				detail(w, 422, "invalid active_only")
				return
			}
		}
		kind := r.URL.Query().Get("job_type")
		if kind != "" && kind != "fixed-one-on-one" && kind != "configuration-space" {
			detail(w, 422, "invalid job_type")
			return
		}
		statuses := []jobs.Status{}
		for _, value := range r.URL.Query()["status"] {
			status := jobs.Status(value)
			switch status {
			case jobs.Pending, jobs.Preparing, jobs.Running, jobs.Succeeded, jobs.CompletedWithFailures, jobs.CancelRequested, jobs.Cancelled, jobs.Failed:
				statuses = append(statuses, status)
			default:
				detail(w, 422, "unknown job status")
				return
			}
		}
		page, err := store.List(r.Context(), statuses, active, kind, offset, limit)
		if err != nil {
			jobError(w, err)
			return
		}
		items := make([]jobSummary, 0, len(page))
		for _, job := range page {
			view, err := summary(r.Context(), store, job)
			if err != nil {
				jobError(w, err)
				return
			}
			items = append(items, view)
		}
		var cursor *string
		if len(items) == limit {
			value := strconv.Itoa(offset + len(items))
			cursor = &value
		}
		writeJSON(w, 200, struct {
			Items      []jobSummary `json:"items"`
			NextCursor *string      `json:"next_cursor"`
		}{items, cursor})
	})
	mux.HandleFunc("GET /v1/inference/jobs/{job_id}", func(w http.ResponseWriter, r *http.Request) {
		job, err := store.Get(r.Context(), r.PathValue("job_id"))
		if err != nil {
			jobError(w, err)
			return
		}
		view, err := summary(r.Context(), store, job)
		if err != nil {
			jobError(w, err)
			return
		}
		writeJSON(w, 200, view)
	})
	mux.HandleFunc("POST /v1/inference/jobs/{job_id}/cancel", func(w http.ResponseWriter, r *http.Request) {
		job, err := store.RequestCancel(r.Context(), r.PathValue("job_id"), time.Now().UTC())
		if err != nil {
			jobError(w, err)
			return
		}
		view, err := summary(r.Context(), store, job)
		if err != nil {
			jobError(w, err)
			return
		}
		writeJSON(w, 200, struct {
			Job jobSummary `json:"job"`
		}{view})
	})
}
