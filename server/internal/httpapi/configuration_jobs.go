package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"pokemonbattleinference/server/internal/jobs"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// configurationJobStatus 保留原 configuration-jobs 独立 DTO，不能复用通用 jobs 的细状态字段。
type configurationJobStatus struct {
	ID                    string      `json:"job_id"`
	Status                string      `json:"status"`
	CancellationRequested bool        `json:"cancellation_requested"`
	Counts                jobCounts   `json:"counts"`
	Nodes                 jobResource `json:"state_nodes"`
	Edges                 jobResource `json:"state_edges"`
	Ruleset               string      `json:"ruleset_id"`
	Version               int         `json:"version_group_id"`
	Revision              string      `json:"calculation_revision"`
	Weight                string      `json:"weight_assumption"`
	AttackerPolicy        string      `json:"attacker_policy"`
	DefenderPolicy        string      `json:"defender_policy"`
	FailureCode           *string     `json:"last_failure_code"`
	Diagnostic            *string     `json:"last_failure_diagnostic"`
	Created               string      `json:"created_at"`
	Updated               string      `json:"updated_at"`
	Completed             *string     `json:"completed_at"`
}

// configurationProbability 是原任意精度概率的展示视图；只在 decimal 字段转换为浮点。
type configurationProbability struct {
	Numerator   string  `json:"numerator"`
	Denominator string  `json:"denominator"`
	Decimal     float64 `json:"decimal"`
}

// configurationCaseView 保留原分页项所有字段/null；不加载完整战斗图或调用计算器。
type configurationCaseView struct {
	ID            string                    `json:"configuration_id"`
	Sequence      int                       `json:"sequence_no"`
	Status        jobs.Status               `json:"status"`
	Attacker      int                       `json:"attacker_pokemon_id"`
	Defender      int                       `json:"defender_pokemon_id"`
	AttackerMoves []int                     `json:"attacker_move_ids"`
	DefenderMoves []int                     `json:"defender_move_ids"`
	AttackerWin   *configurationProbability `json:"attacker_win_probability"`
	DefenderWin   *configurationProbability `json:"defender_win_probability"`
	Draw          *configurationProbability `json:"draw_probability"`
	ExpectedKind  *string                   `json:"expected_turns_kind"`
	ExpectedText  *string                   `json:"expected_turns"`
	Nodes         int64                     `json:"node_count"`
	Edges         int64                     `json:"edge_count"`
	Explanation   json.RawMessage           `json:"explanation"`
	FailureCode   *string                   `json:"failure_code"`
	Diagnostic    *string                   `json:"diagnostic"`
	Attempts      int                       `json:"attempt_count"`
}

// configurationCasePage 是过滤后总数与稳定 sequence 分页，next_cursor 只在仍有后页时存在。
type configurationCasePage struct {
	JobID  string                  `json:"job_id"`
	Offset int                     `json:"offset"`
	Limit  int                     `json:"limit"`
	Total  int                     `json:"total"`
	Next   *string                 `json:"next_cursor"`
	Items  []configurationCaseView `json:"items"`
}

// publicConfigurationStatus 沿原 presenter 压缩生命周期；cancel_requested 仍显示 running。
func publicConfigurationStatus(status jobs.Status) string {
	switch status {
	case jobs.Pending, jobs.Preparing:
		return "queued"
	case jobs.Running, jobs.CancelRequested:
		return "running"
	case jobs.Succeeded:
		return "completed"
	case jobs.CompletedWithFailures:
		return "partial"
	case jobs.Cancelled:
		return "cancelled"
	default:
		return "failed"
	}
}

// pythonTimestamp 保留原 datetime.isoformat 的显式 UTC offset 与按需六位微秒，避免 JSON 文本漂移。
func pythonTimestamp(value time.Time) string {
	format := "2006-01-02T15:04:05"
	if value.Nanosecond() != 0 {
		format += ".000000"
	}
	return value.UTC().Format(format + "-07:00")
}

// configurationStatusView 将已持久化 job 与冻结 spec 映射原轮询响应，不使用当前进程的默认预算。
func configurationStatusView(job jobs.Job) configurationJobStatus {
	c := job.Counts
	result := configurationJobStatus{ID: job.ID, Status: publicConfigurationStatus(job.Status), CancellationRequested: job.Status == jobs.CancelRequested, Counts: jobCounts{c.Total, c.Pending, c.Running, c.Succeeded, c.Failed, c.Truncated, c.Cancelled, c.Succeeded + c.Failed + c.Truncated + c.Cancelled}, Nodes: jobResource{c.Nodes, int64(c.Total) * int64(job.Spec.MaxNodes)}, Edges: jobResource{c.Edges, int64(c.Total) * int64(job.Spec.MaxEdges)}, Ruleset: job.RulesetID, Version: job.VersionGroupID, Revision: job.Revision, Weight: job.Spec.WeightAssumption, AttackerPolicy: job.Spec.AttackerPolicy, DefenderPolicy: job.Spec.DefenderPolicy, FailureCode: job.FailureCode, Diagnostic: job.Diagnostic, Created: pythonTimestamp(job.CreatedAt), Updated: pythonTimestamp(job.UpdatedAt)}
	if job.CompletedAt != nil {
		value := pythonTimestamp(*job.CompletedAt)
		result.Completed = &value
	}
	return result
}

// pythonRepr 在旧错误 envelope 中保留 repr(id) 的引号/控制字符/Unicode 表示；不读取文件或执行输入。
func pythonRepr(value string) string {
	quote := '\''
	if strings.ContainsRune(value, '\'') && !strings.ContainsRune(value, '"') {
		quote = '"'
	}
	var output strings.Builder
	output.WriteRune(quote)
	for _, character := range value {
		switch {
		case character == quote || character == '\\':
			output.WriteRune('\\')
			output.WriteRune(character)
		case character == '\n':
			output.WriteString(`\n`)
		case character == '\r':
			output.WriteString(`\r`)
		case character == '\t':
			output.WriteString(`\t`)
		case !unicode.IsPrint(character) && character < 256:
			fmt.Fprintf(&output, `\x%02x`, character)
		case !unicode.IsPrint(character) && character <= 65535:
			fmt.Fprintf(&output, `\u%04x`, character)
		case !unicode.IsPrint(character):
			fmt.Fprintf(&output, `\U%08x`, character)
		default:
			output.WriteRune(character)
		}
	}
	output.WriteRune(quote)
	return output.String()
}

// configurationJobError 只公开原业务错误 envelope，存储故障不输出连接、SQL 或驱动异常。
func configurationJobError(w http.ResponseWriter, id string, err error) {
	if errors.Is(err, jobs.ErrNotFound) {
		writeJSON(w, 404, struct {
			Detail struct {
				Code    string `json:"code"`
				Message string `json:"message"`
			} `json:"detail"`
		}{Detail: struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		}{"battle_inference_job_not_found", "battle inference job " + pythonRepr(id) + " was not found"}})
		return
	}
	detail(w, 503, "job storage unavailable")
}

// probabilityView 规范化只读 fraction 的精确字符串并提供原展示小数；nil 仍为 null。
func probabilityView(fraction *jobs.Fraction) (*configurationProbability, error) {
	if fraction == nil {
		return nil, nil
	}
	value, ok := new(big.Rat).SetString(fraction.Numerator + "/" + fraction.Denominator)
	if !ok || value.Sign() < 0 || value.Cmp(big.NewRat(1, 1)) > 0 {
		return nil, errors.New("invalid persisted probability")
	}
	decimal, _ := value.Float64()
	return &configurationProbability{value.Num().String(), value.Denom().String(), decimal}, nil
}

// configurationPokemonIDs 只解码旧 canonical 身份以读取展示 ID，不生成或枚举任何配置。
// value 必须是原六字段配置对、每侧七字段身份数组；失败阻止输出误配的宝可梦/结果。
func configurationPokemonIDs(value string) ([2]int, error) {
	var result [2]int
	const prefix = "one-on-one-configuration:"
	if !strings.HasPrefix(value, prefix) {
		return result, errors.New("invalid canonical configuration identity")
	}
	var payload []json.RawMessage
	if err := json.Unmarshal([]byte(strings.TrimPrefix(value, prefix)), &payload); err != nil || len(payload) != 6 {
		return result, errors.New("invalid canonical configuration identity")
	}
	var contract, ruleset, revision string
	var version int
	if json.Unmarshal(payload[0], &contract) != nil || contract != "one-on-one-move-pool.v1" || json.Unmarshal(payload[1], &ruleset) != nil || json.Unmarshal(payload[2], &version) != nil || version <= 0 || json.Unmarshal(payload[3], &revision) != nil {
		return result, errors.New("invalid canonical rule axis")
	}
	for _, text := range []string{ruleset, revision} {
		if text == "" || text != strings.TrimSpace(text) {
			return result, errors.New("invalid canonical rule axis")
		}
	}
	for index := range result {
		var fields []json.RawMessage
		if json.Unmarshal(payload[4+index], &fields) != nil || len(fields) != 7 {
			return result, errors.New("invalid canonical side identity")
		}
		var form *int
		var level int
		var profile, ability string
		var item *string
		var moves []int
		if json.Unmarshal(fields[0], &result[index]) != nil || result[index] <= 0 || json.Unmarshal(fields[1], &form) != nil || (form != nil && *form <= 0) || json.Unmarshal(fields[2], &level) != nil || level < 1 || level > 100 || json.Unmarshal(fields[3], &profile) != nil || json.Unmarshal(fields[4], &ability) != nil || json.Unmarshal(fields[5], &item) != nil || json.Unmarshal(fields[6], &moves) != nil || len(moves) < 1 || len(moves) > 4 {
			return result, errors.New("invalid canonical side identity")
		}
		texts := []string{profile, ability}
		if item != nil {
			texts = append(texts, *item)
		}
		for _, text := range texts {
			if text == "" || text != strings.TrimSpace(text) {
				return result, errors.New("invalid canonical side text")
			}
		}
		seen := map[int]bool{}
		for _, move := range moves {
			if move <= 0 || seen[move] {
				return result, errors.New("invalid canonical move identity")
			}
			seen[move] = true
		}
	}
	return result, nil
}

// configurationCase 将同一行 case/result 转成原展示 DTO；历史非对象 explanation 与原 presenter 一样输出 null。
func configurationCase(item jobs.Case) (configurationCaseView, error) {
	ids, err := configurationPokemonIDs(item.Definition.PairID)
	if err != nil {
		return configurationCaseView{}, err
	}
	view := configurationCaseView{ID: item.Definition.PairID, Sequence: item.Sequence, Status: item.Status, Attacker: ids[0], Defender: ids[1], AttackerMoves: item.Definition.AttackerMoves, DefenderMoves: item.Definition.DefenderMoves, Attempts: item.Attempts}
	if item.Result == nil {
		return view, nil
	}
	result := item.Result
	if view.AttackerWin, err = probabilityView(result.AttackerWin); err != nil {
		return view, err
	}
	if view.DefenderWin, err = probabilityView(result.DefenderWin); err != nil {
		return view, err
	}
	if view.Draw, err = probabilityView(result.Draw); err != nil {
		return view, err
	}
	view.Nodes, view.Edges, view.FailureCode, view.Diagnostic = result.Nodes, result.Edges, result.FailureCode, result.Diagnostic
	if result.ExpectedTurns != nil {
		kind, text := result.ExpectedTurns.Kind, result.ExpectedTurns.Kind
		if result.ExpectedTurns.Value != nil {
			text = result.ExpectedTurns.Value.Numerator + "/" + result.ExpectedTurns.Value.Denominator
		}
		view.ExpectedKind, view.ExpectedText = &kind, &text
	}
	if result.Explanation != nil {
		var object map[string]json.RawMessage
		if json.Unmarshal([]byte(*result.Explanation), &object) == nil && object != nil {
			view.Explanation = json.RawMessage(*result.Explanation)
		}
	}
	return view, nil
}

// configurationPage 读取原 filter 的稳定页面；ctx 取消 SQL，任一身份/结果损坏不输出部分成功。
func configurationPage(ctx context.Context, store *jobs.Store, id string, filter jobs.CaseFilter) (configurationCasePage, error) {
	items, total, err := store.FilteredCases(ctx, id, filter)
	if err != nil {
		return configurationCasePage{}, err
	}
	page := configurationCasePage{JobID: id, Offset: filter.Offset, Limit: filter.Limit, Total: total, Items: make([]configurationCaseView, 0, len(items))}
	for _, item := range items {
		view, err := configurationCase(item)
		if err != nil {
			return configurationCasePage{}, err
		}
		page.Items = append(page.Items, view)
	}
	if next := filter.Offset + len(items); next < total {
		cursor := strconv.Itoa(next)
		page.Next = &cursor
	}
	return page, nil
}

// configurationQueryInt 沿原 FastAPI 单值 query 采用最后一项；显式空值不能冒用缺省值。
// name 为参数名，fallback 为省略默认，minimum/maximum 是协议范围；失败写入422并返回false。
func configurationQueryInt(w http.ResponseWriter, r *http.Request, name string, fallback, minimum, maximum int) (int, bool) {
	values, exists := r.URL.Query()[name]
	if !exists {
		return fallback, true
	}
	value := ""
	if len(values) > 0 {
		value = values[len(values)-1]
	}
	parsed, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil || parsed < minimum || parsed > maximum {
		detail(w, 422, "invalid "+name)
		return 0, false
	}
	return parsed, true
}

// registerConfigurationJobs 迁移原配置任务四条读取/取消 API；不受理尚未完成严格准入的创建命令。
// mux 是主 router；db 是借用连接池；原 Python 创建且没有 Go definition 的任务也能读取。
func registerConfigurationJobs(mux *http.ServeMux, db *sql.DB) {
	registerConfigurationJobMetadata(mux, db)
	store := jobs.New(db)
	mux.HandleFunc("GET /v1/inference/configuration-jobs/{job_id}", func(w http.ResponseWriter, r *http.Request) {
		job, err := store.Get(r.Context(), r.PathValue("job_id"))
		if err != nil {
			configurationJobError(w, r.PathValue("job_id"), err)
			return
		}
		writeJSON(w, 200, configurationStatusView(job))
	})
	mux.HandleFunc("POST /v1/inference/configuration-jobs/{job_id}/cancel", func(w http.ResponseWriter, r *http.Request) {
		job, err := store.RequestCancel(r.Context(), r.PathValue("job_id"), time.Now().UTC())
		if err != nil {
			configurationJobError(w, r.PathValue("job_id"), err)
			return
		}
		writeJSON(w, 200, struct {
			ID        string `json:"job_id"`
			Requested bool   `json:"cancellation_requested"`
			Status    string `json:"status"`
		}{job.ID, job.Status == jobs.CancelRequested || job.Status == jobs.Cancelled, publicConfigurationStatus(job.Status)})
	})
	mux.HandleFunc("GET /v1/inference/configuration-jobs/{job_id}/results", func(w http.ResponseWriter, r *http.Request) {
		offset, ok := configurationQueryInt(w, r, "offset", 0, 0, 2147483647)
		if !ok {
			return
		}
		limit, ok := configurationQueryInt(w, r, "limit", 100, 1, 500)
		if !ok {
			return
		}
		filter := jobs.CaseFilter{Offset: offset, Limit: limit}
		if values, exists := r.URL.Query()["status"]; exists {
			value := ""
			if len(values) > 0 {
				value = values[len(values)-1]
			}
			filter.Statuses = []jobs.Status{jobs.Status(value)}
		}
		if err := filter.Validate(); err != nil {
			detail(w, 422, pythonRepr(string(filter.Statuses[0]))+" is not a valid BattleInferenceCaseStatus")
			return
		}
		page, err := configurationPage(r.Context(), store, r.PathValue("job_id"), filter)
		if err != nil {
			configurationJobError(w, r.PathValue("job_id"), err)
			return
		}
		writeJSON(w, 200, page)
	})
	mux.HandleFunc("GET /v1/inference/configuration-jobs/{job_id}/issues", func(w http.ResponseWriter, r *http.Request) {
		offset := 0
		if values, exists := r.URL.Query()["cursor"]; exists {
			value := ""
			if len(values) > 0 {
				value = values[len(values)-1]
			}
			parsed, err := strconv.Atoi(strings.TrimSpace(value))
			if err != nil {
				detail(w, 422, "cursor must be an integer offset")
				return
			}
			if parsed < 0 {
				detail(w, 422, "offset must be non-negative")
				return
			}
			offset = parsed
		}
		limit, ok := configurationQueryInt(w, r, "limit", 100, 1, 500)
		if !ok {
			return
		}
		filter := jobs.CaseFilter{Statuses: []jobs.Status{jobs.Failed, jobs.Truncated}, Offset: offset, Limit: limit}
		if values, exists := r.URL.Query()["status"]; exists {
			value := ""
			if len(values) > 0 {
				value = values[len(values)-1]
			}
			if value != "failed" && value != "truncated" {
				detail(w, 422, "invalid issue status")
				return
			}
			filter.Statuses = []jobs.Status{jobs.Status(value)}
		}
		if values, exists := r.URL.Query()["error_code"]; exists {
			value := ""
			if len(values) > 0 {
				value = values[len(values)-1]
			}
			filter.FailureCodes = []string{value}
		}
		if err := filter.Validate(); err != nil {
			detail(w, 422, pythonRepr(filter.FailureCodes[0])+" is not a valid BattleInferenceFailureCode")
			return
		}
		page, err := configurationPage(r.Context(), store, r.PathValue("job_id"), filter)
		if err != nil {
			configurationJobError(w, r.PathValue("job_id"), err)
			return
		}
		writeJSON(w, 200, page)
	})
}
