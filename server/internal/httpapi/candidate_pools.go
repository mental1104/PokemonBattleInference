package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"pokemonbattleinference/server/internal/catalog"
	"strings"
	"time"
)

// candidatePoolHandler 读取同一version-aware知识快照，所有支持/缺失机制/原因判定由真实Core负责。
type candidatePoolHandler struct {
	store *catalog.Store
	core  calculatorHandler
}

// registerCandidatePools 挂接原候选池GET；只投影公开moves，不隐藏不可选择候选。
func registerCandidatePools(mux *http.ServeMux, db *sql.DB) {
	mux.Handle("GET /v1/inference/candidate-pools/{pokemon_id}", candidatePoolHandler{catalog.New(db), calculatorHandler{worker: configuredWorker()}})
}

// candidatePoolAdmission 是原页面投影；disabled_reason只随Core的selectable展示同一个reason。
type candidatePoolAdmission struct {
	Status     string   `json:"status"`
	Selectable bool     `json:"selectable"`
	Reason     string   `json:"reason"`
	Disabled   *string  `json:"disabled_reason"`
	Missing    []string `json:"missing_mechanism_identifiers"`
}

// candidatePoolMove 保留全部合法招式的原类型/威力/null，以及独立Core准入结果。
type candidatePoolMove struct {
	ID         int                    `json:"move_id"`
	Identifier string                 `json:"identifier"`
	Name       string                 `json:"display_name"`
	Type       string                 `json:"type_identifier"`
	TypeName   string                 `json:"type_name"`
	Category   string                 `json:"damage_class"`
	Power      *int                   `json:"power"`
	Admission  candidatePoolAdmission `json:"admission"`
}

// candidatePoolError 返回原候选池专属业务envelope；message只能含安全的规则/ID说明。
func candidatePoolError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"detail": map[string]string{"code": code, "message": message}})
}

// ServeHTTP 先核对显式规则轴，再从单次RR快照把全部合法move事实交子进程；ctx超时中断查询和Core。
func (handler candidatePoolHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	id, ok := pokemonID(w, r)
	if !ok {
		return
	}
	axes, exists := r.URL.Query()["ruleset_id"]
	if !exists || len(axes) == 0 {
		detail(w, 422, "ruleset_id and version_group_id are required")
		return
	}
	axis := axes[len(axes)-1]
	if axis == "" {
		detail(w, 422, "ruleset_id and version_group_id are required")
		return
	}
	if _, exists := r.URL.Query()["version_group_id"]; !exists {
		detail(w, 422, "ruleset_id and version_group_id are required")
		return
	}
	version, ok := configurationQueryInt(w, r, "version_group_id", 0, 1, 2147483647)
	if !ok {
		return
	}
	if axis != strings.TrimSpace(axis) {
		candidatePoolError(w, 422, "battle_candidate_pool_invalid_request", "ruleset_id must be a non-empty normalized identifier")
		return
	}
	if axis != "pokemon-champion" {
		candidatePoolError(w, 422, "battle_candidate_pool_invalid_request", "effect factory ruleset does not match candidate command")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	snapshot, err := handler.store.Inference(ctx, axis, version, []int{id})
	if err != nil {
		var input *catalog.CalculationInputError
		if errors.As(err, &input) {
			message := "battle inference ruleset context was not found"
			if strings.HasPrefix(input.Error(), "pokemon ") {
				message = fmt.Sprintf("pokemon profile %d was not found", id)
			}
			candidatePoolError(w, 404, "battle_candidate_pool_not_found", message)
		} else if ctx.Err() != nil {
			calculatorFailure(w, ctx.Err())
		} else {
			detail(w, 503, "catalog storage unavailable")
		}
		return
	}
	moves := snapshot.Pokemon[0].Moves
	candidates := make([]jobAdmissionCandidate, 0, len(moves))
	for _, move := range moves {
		candidates = append(candidates, jobAdmissionCandidate{Source: "move", Effect: move.Effect, Mechanism: move.Capability.Identifier, RepositoryReason: move.Capability.Reason, BaseExecutable: move.Category == "status" || move.Power != nil, AllowNoEffect: move.Category != "status" && move.Effect == nil})
	}
	// 使用与原HTTP相同的factory reconciliation+strict，不在Go复制能力覆盖或reason拼接规则。
	input := struct {
		Mode       string                  `json:"mode"`
		Factory    string                  `json:"factory"`
		Repository string                  `json:"repository_mode"`
		Candidates []jobAdmissionCandidate `json:"candidates"`
	}{"admission", "transparent_inference", "factory_reconciled", candidates}
	results, err := handler.core.batch(ctx, []any{struct {
		Kind  string `json:"kind"`
		Input any    `json:"input"`
	}{"configuration_coverage", input}})
	if err != nil {
		calculatorFailure(w, err)
		return
	}
	var decisions struct {
		Kind       string                 `json:"kind"`
		Candidates []jobAdmissionDecision `json:"candidates"`
	}
	if json.Unmarshal(results[0], &decisions) != nil || decisions.Kind != "configuration_coverage" || len(decisions.Candidates) != len(moves) {
		detail(w, 500, "invalid native candidate response")
		return
	}
	output := make([]candidatePoolMove, 0, len(moves))
	for index, move := range moves {
		decision := decisions.Candidates[index]
		admission := candidatePoolAdmission{Status: decision.Status, Selectable: decision.Selectable, Reason: decision.Reason, Missing: decision.Missing}
		if !decision.Selectable {
			reason := decision.Reason
			admission.Disabled = &reason
		}
		output = append(output, candidatePoolMove{move.ID, move.Identifier, move.Name, move.Type.Identifier, move.Type.Name, move.Category, move.Power, admission})
	}
	writeJSON(w, 200, struct {
		ID       int                 `json:"pokemon_id"`
		Ruleset  string              `json:"ruleset_id"`
		Version  int                 `json:"version_group_id"`
		Revision string              `json:"calculation_revision"`
		Moves    []candidatePoolMove `json:"moves"`
	}{id, axis, version, "battle-inference.summary-exploration.v2", output})
}
