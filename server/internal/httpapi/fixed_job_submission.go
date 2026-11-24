package httpapi

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"pokemonbattleinference/server/internal/catalog"
	"pokemonbattleinference/server/internal/jobs"
	"reflect"
	"slices"
	"sort"
	"strings"
	"time"
	"unicode/utf16"
	"unicode/utf8"
)

// fixedJobSubmissionHandler 适配原固定任务创建合同；复用真实strict/单case规划及PG执行模板。
// 不调用同步solver，未知stat profile仍冻结为worker准备失败，而不是提前改变原202合同。
type fixedJobSubmissionHandler struct{ submission jobSubmissionHandler }

// registerFixedJobSubmission 将原固定请求挂接到真实任务仓库；db必须是已初始化运行表的连接池。
func registerFixedJobSubmission(mux *http.ServeMux, db *sql.DB) {
	mux.Handle("POST /v1/inference/fixed-one-on-one-jobs", fixedJobSubmissionHandler{jobSubmissionHandler{catalog.New(db), jobs.New(db), calculatorHandler{worker: configuredWorker()}}})
}

// fixedJobInvalid 返回原固定任务ValueError的稳定422；message仅包含安全输入诊断。
func fixedJobInvalid(w http.ResponseWriter, message string) {
	writeJSON(w, 422, map[string]any{"detail": map[string]string{"code": "fixed_battle_job_invalid_request", "message": message}})
}

// fixedSubmissionRequest 只映射原固定请求到既有move-pool命令，Core负责唯一case/canonical/准入。
// input须通过HTTP校验；返回新切片以免排序改变原请求，预算和两种策略保持原明确值。
func fixedSubmissionRequest(input inferenceFixedRequest) jobSubmissionRequest {
	turns := input.Limits.Turns
	result := jobSubmissionRequest{jobPoolCommand: jobPoolCommand{Contract: "one-on-one-move-pool.v1", Ruleset: input.Ruleset, Version: input.Version, Revision: "battle-inference.summary-exploration.v2", Dimensions: jobDimensions{"fixed", "fixed", "fixed", "fixed", "fixed", "fixed", "candidate_pool", "disabled"}, Weight: "uniform_configuration_pair", AttackerPolicy: inferencePolicy(input.AttackerPolicy), DefenderPolicy: inferencePolicy(input.DefenderPolicy), Mechanism: "supported_only", Attacker: jobSelection{input.Attacker.jobFixed, append([]int{}, input.Attacker.Moves...)}, Defender: jobSelection{input.Defender.jobFixed, append([]int{}, input.Defender.Moves...)}}, Execution: jobExecutionBudget{1, 1, input.Limits.Nodes, input.Limits.Edges, &turns}}
	sort.Ints(result.Attacker.Moves)
	sort.Ints(result.Defender.Moves)
	return result
}

// fixedSubmissionID 保留原仅绑定header key的SHA；同key不同选择将在PG不可变定义检查中409。
// key已校验为非空normalized UTF8，编码与Python ensure_ascii=True紧凑JSON一致。
func fixedSubmissionID(key string) (string, error) {
	var encoded strings.Builder
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode([]string{"fixed-one-on-one", key}); err != nil {
		return "", err
	}
	var ascii strings.Builder
	for _, character := range strings.TrimSuffix(encoded.String(), "\n") {
		if character < 128 {
			ascii.WriteRune(character)
		} else if character <= 65535 {
			fmt.Fprintf(&ascii, `\u%04x`, character)
		} else {
			first, second := utf16.EncodeRune(character)
			fmt.Fprintf(&ascii, `\u%04x\u%04x`, first, second)
		}
	}
	digest := sha256.Sum256([]byte(ascii.String()))
	return "fixed-one-on-one-job-" + hex.EncodeToString(digest[:]), nil
}

// ServeHTTP 在30秒ctx内读取同快照、执行strict规划并原子冻结单case；取消不留下半份任务。
// r正文使用原固定DTO且忽略extra字段；响应202是提交确认，实际完成状态从真实PG读取。
func (handler fixedJobSubmissionHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	var input inferenceFixedRequest
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20))
	if decoder.Decode(&input) != nil {
		detail(w, 422, "invalid fixed battle request")
		return
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		detail(w, 422, "request must contain one JSON value")
		return
	}
	if err := input.validate(); err != nil {
		message := err.Error()
		if message == "move_ids must be unique" {
			message = "candidate move ids must be unique"
		}
		if message == "move_ids must contain positive integers" {
			message = "candidate move ids must be positive integers"
		}
		fixedJobInvalid(w, message)
		return
	}
	keys, exists := r.Header["Idempotency-Key"]
	if !exists || len(keys) == 0 || keys[0] == "" || utf8.RuneCountInString(keys[0]) > 200 {
		detail(w, 422, "Idempotency-Key is required and must contain 1..200 characters")
		return
	}
	key := keys[0]
	if key != strings.TrimSpace(key) {
		fixedJobInvalid(w, "idempotency_key is required for fixed battle jobs")
		return
	}
	request := fixedSubmissionRequest(input)
	if input.Ruleset != "pokemon-champion" {
		fixedJobInvalid(w, "effect factory ruleset does not match candidate command")
		return
	}
	snapshot, err := handler.submission.catalog.Inference(ctx, input.Ruleset, input.Version, []int{input.Attacker.PokemonID, input.Defender.PokemonID})
	if err != nil {
		var invalid *catalog.CalculationInputError
		if errors.As(err, &invalid) {
			message := "battle inference ruleset context was not found"
			var id int
			if _, scanErr := fmt.Sscanf(invalid.Error(), "pokemon %d is not available", &id); scanErr == nil {
				message = fmt.Sprintf("pokemon profile %d was not found", id)
			}
			inferenceFailure(w, &inferenceRequestError{status: 404, code: "fixed_battle_candidate_pool_not_found", message: message})
		} else if ctx.Err() != nil {
			calculatorFailure(w, ctx.Err())
		} else {
			detail(w, 503, "catalog storage unavailable")
		}
		return
	}
	definition, failures, err := handler.submission.prepare(ctx, request, snapshot, "")
	if err != nil {
		inferenceFailure(w, err)
		return
	}
	if len(failures) > 0 {
		parts := make([]string, 0, len(failures))
		for _, failure := range failures {
			parts = append(parts, failure.Source+":"+failure.Requested+":"+failure.Status+":missing="+strings.Join(failure.Missing, ","))
		}
		inferenceFailure(w, &inferenceRequestError{status: 422, code: "fixed_battle_mechanism_rejected", message: "strict mechanism admission rejected: " + strings.Join(parts, "; "), failures: failures})
		return
	}
	definition.ID, err = fixedSubmissionID(key)
	if err != nil {
		inferenceFailure(w, err)
		return
	}
	if len(definition.Cases) != 1 {
		detail(w, 503, "fixed job planner did not return one case")
		return
	}
	// 原固定任务ID只由key决定；PG拒绝已存在不同定义，绝不覆写原任务或重置进度。
	if _, err = handler.submission.store.Create(ctx, definition, time.Now().UTC().Truncate(time.Microsecond)); err != nil {
		if errors.Is(err, jobs.ErrConflict) {
			matches, loadErr := handler.matchesExisting(ctx, definition)
			if loadErr != nil {
				if ctx.Err() != nil {
					calculatorFailure(w, ctx.Err())
				} else {
					detail(w, 503, "job storage unavailable")
				}
				return
			}
			if !matches {
				writeJSON(w, 409, map[string]any{"detail": map[string]string{"code": "fixed_battle_job_idempotency_conflict", "message": fmt.Sprintf("battle inference job '%s' already exists", definition.ID)}})
				return
			}
		} else {
			if ctx.Err() != nil {
				calculatorFailure(w, ctx.Err())
			} else {
				detail(w, 503, "job storage unavailable")
			}
			return
		}
	}
	job, err := handler.submission.store.Get(ctx, definition.ID)
	if err != nil {
		detail(w, 503, "job storage unavailable")
		return
	}
	writeJSON(w, 202, struct {
		ID      string      `json:"job_id"`
		Type    string      `json:"job_type"`
		Status  jobs.Status `json:"status"`
		Phase   string      `json:"phase"`
		Created string      `json:"created_at"`
		Count   int         `json:"submitted_configuration_pairs"`
		Links   jobLinks    `json:"links"`
	}{job.ID, "fixed-one-on-one", job.Status, "queued", pythonTimestamp(job.CreatedAt), 1, jobLinks{"/v1/inference/jobs/" + job.ID, "/v1/inference/jobs/" + job.ID + "/cancel"}})
}

// matchesExisting 保留原固定任务只比较规格/规则/canonical单case的幂等合同。
// ctx取消终止PG读取；definition是新请求已通过strict的冻结值。只读历史任务，不补写或认领旧执行模板。
// 元数据版本变化或旧Python没有Go definition不应把同一个原请求误报冲突；读失败单独返回error。
func (handler fixedJobSubmissionHandler) matchesExisting(ctx context.Context, definition jobs.Definition) (bool, error) {
	existing, err := handler.submission.store.Get(ctx, definition.ID)
	if err != nil {
		return false, err
	}
	if existing.RulesetID != definition.RulesetID || existing.VersionGroupID != definition.VersionGroupID || !reflect.DeepEqual(existing.Spec, definition.Spec) {
		return false, nil
	}
	cases, total, err := handler.submission.store.Cases(ctx, definition.ID, nil, 0, 1)
	if err != nil {
		return false, err
	}
	if total != 1 || len(cases) != 1 || len(definition.Cases) != 1 {
		return false, nil
	}
	prior, next := cases[0].Definition, definition.Cases[0]
	return prior.PairID == next.PairID && prior.AttackerID == next.AttackerID && prior.DefenderID == next.DefenderID && slices.Equal(prior.AttackerMoves, next.AttackerMoves) && slices.Equal(prior.DefenderMoves, next.DefenderMoves), nil
}
