package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"pokemonbattleinference/server/internal/catalog"
	"pokemonbattleinference/server/internal/configurations"
	"pokemonbattleinference/server/internal/jobs"
	"pokemonbattleinference/server/internal/nativeworker"
	"strconv"
	"strings"
	"time"
)

// fixedInferenceHandler 复用真实知识/既有模板和独立Core，不调用Python或在Go实现战斗规则。
type fixedInferenceHandler struct {
	store *catalog.Store
	core  calculatorHandler
}

// registerFixedInference 挂接原summary-only路由；mux与db由调用方拥有，不启动后台生命周期。
func registerFixedInference(mux *http.ServeMux, db *sql.DB) {
	handler := fixedInferenceHandler{catalog.New(db), calculatorHandler{worker: configuredWorker()}}
	mux.HandleFunc("POST /v1/inference/fixed-one-on-one", handler.summary)
}

// inferenceRequestError 区分旧业务拒绝与基础设施错误，不携带SQL/连接串或worker路径。
type inferenceRequestError struct {
	status   int
	code     string
	message  string
	failures []jobAdmissionFailure
}

// Error 返回该业务边界的稳定诊断，完整HTTP字段由统一适配器编码。
func (failure *inferenceRequestError) Error() string { return failure.message }

// inferenceFailure 只格式化原fixed路由envelope；其他取消/子进程错误复用既有隔离适配。
// w接收最终失败；err是当前请求产生的独立错误，不输出潜在敏感底层诊断。
func inferenceFailure(w http.ResponseWriter, err error) {
	var failure *inferenceRequestError
	if !errors.As(err, &failure) {
		calculatorFailure(w, err)
		return
	}
	response := map[string]any{"code": failure.code, "message": failure.message}
	if failure.failures != nil {
		// rejected 保留原fixed失败条目的公开字段，避免引入job专属source字段。
		type rejected struct {
			Requested string   `json:"requested_identifier"`
			Status    string   `json:"status"`
			Reason    string   `json:"reason"`
			Missing   []string `json:"missing_mechanism_identifiers"`
		}
		values := make([]rejected, 0, len(failure.failures))
		for _, item := range failure.failures {
			values = append(values, rejected{item.Requested, item.Status, item.Reason, item.Missing})
		}
		response["failures"] = values
	}
	writeJSON(w, failure.status, map[string]any{"detail": response})
}

// inferenceInvalid 保留原fixed请求的业务错误码，message只能是安全的协议诊断。
func inferenceInvalid(message string) error {
	return &inferenceRequestError{status: 422, code: "fixed_battle_invalid_request", message: message}
}

// summary 用同一30秒ctx读取一次RR快照，全部能力/组合/机制/求解均走独立Core。
// w只在完整结果或稳定失败确定后写出；r取消传播到PG和每次child调用。
func (handler fixedInferenceHandler) summary(w http.ResponseWriter, r *http.Request) {
	var input inferenceFixedRequest
	if !decodeJSON(w, r, &input) {
		return
	}
	if err := input.validate(); err != nil {
		inferenceFailure(w, inferenceInvalid(err.Error()))
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	prepared, err := handler.prepare(ctx, input)
	if err != nil {
		inferenceFailure(w, err)
		return
	}
	result, err := handler.solve(ctx, input, prepared)
	if err != nil {
		inferenceFailure(w, err)
		return
	}
	writeJSON(w, 200, result)
}

// inferenceMoveCandidate 只投影已通过strict的原候选，排序/组合仍交Core执行。
type inferenceMoveCandidate struct {
	ID         int          `json:"move_id"`
	Identifier string       `json:"identifier"`
	Move       *jobMoveSpec `json:"move"`
	Effect     *string      `json:"effect_identifier"`
	Support    string       `json:"support"`
	Reason     string       `json:"reason"`
}

// inferenceMoveInput 保留固定技能组的原provider边界，不在Go生成或排序技能组合。
type inferenceMoveInput struct {
	Candidates []inferenceMoveCandidate `json:"candidates"`
	Requested  []int                    `json:"requested_ids"`
	Slots      []int                    `json:"slot_counts"`
	Maximum    int                      `json:"max_raw_combinations"`
}

// inferenceMetadataInput 请求同一Core工厂的完整能力和旧推演机制集合。
type inferenceMetadataInput struct {
	Mode         string    `json:"mode"`
	Factory      string    `json:"factory"`
	Capabilities bool      `json:"include_capabilities"`
	Moves        []*string `json:"moves"`
	Abilities    []*string `json:"abilities"`
	Items        []*string `json:"items"`
}

// inferenceOperation 是当前业务已知操作的传输封套；input到此JSON边界结束。
type inferenceOperation struct {
	Kind  string `json:"kind"`
	Input any    `json:"input"`
}

// inferenceNativeBattler 只读取已由Core计算的初始状态，未识别字段在原完整请求内仍保留。
type inferenceNativeBattler struct {
	Spec struct {
		ID      int           `json:"pokemon_id"`
		Name    string        `json:"name"`
		Moves   []jobMoveSpec `json:"moves"`
		Pokemon struct {
			Level   int                   `json:"level"`
			Ability string                `json:"ability"`
			Item    string                `json:"item"`
			Stats   configurations.Spread `json:"stats"`
		} `json:"pokemon"`
	} `json:"spec"`
}

// inferencePrepared 拥有同一PG快照派生的完整请求和仅展示用配置，不再次查询数据库。
type inferencePrepared struct {
	operation json.RawMessage
	metadata  inferenceMetadataInput
	attacker  inferencePokemonSummary
	defender  inferencePokemonSummary
}

// prepare 先真实strict再规范技能组/能力/初始状态，整个流程共享ctx与唯一PG快照。
// 返回值只属于本次请求；任何失败不返回可继续执行的半份状态。
func (handler fixedInferenceHandler) prepare(ctx context.Context, input inferenceFixedRequest) (inferencePrepared, error) {
	if input.Ruleset != "pokemon-champion" {
		return inferencePrepared{}, inferenceInvalid("effect factory ruleset does not match candidate command")
	}
	snapshot, err := handler.store.Inference(ctx, input.Ruleset, input.Version, []int{input.Attacker.PokemonID, input.Defender.PokemonID})
	if err != nil {
		var invalid *catalog.CalculationInputError
		if errors.As(err, &invalid) {
			message := "battle inference ruleset context was not found"
			var id int
			if _, scanErr := fmt.Sscanf(invalid.Error(), "pokemon %d is not available", &id); scanErr == nil {
				message = fmt.Sprintf("pokemon profile %d was not found", id)
			}
			return inferencePrepared{}, &inferenceRequestError{status: 404, code: "fixed_battle_candidate_pool_not_found", message: message}
		}
		if ctx.Err() != nil {
			return inferencePrepared{}, ctx.Err()
		}
		return inferencePrepared{}, &inferenceRequestError{status: 503, code: "fixed_battle_storage_unavailable", message: "catalog storage unavailable"}
	}
	selections := []jobSelection{{Fixed: input.Attacker.jobFixed, Moves: input.Attacker.Moves}, {Fixed: input.Defender.jobFixed, Moves: input.Defender.Moves}}
	facts := []jobAdmissionFact{}
	sides := make([]jobSideFacts, 2)
	for index, selection := range selections {
		sides[index], err = appendJobFacts(&facts, selection, snapshot.Pokemon[index], snapshot.Items, input.Version, index)
		if err != nil {
			return inferencePrepared{}, err
		}
	}
	candidates := make([]jobAdmissionCandidate, 0, len(facts))
	metadata := inferenceMetadataInput{Mode: "describe", Factory: "transparent_inference", Capabilities: true, Moves: []*string{}, Abilities: []*string{}, Items: []*string{}}
	for _, fact := range facts {
		candidates = append(candidates, fact.jobAdmissionCandidate)
		switch fact.Source {
		case "move":
			if fact.Effect != nil {
				metadata.Moves = append(metadata.Moves, fact.Effect)
			}
		case "ability":
			metadata.Abilities = append(metadata.Abilities, fact.Effect)
		case "item":
			metadata.Items = append(metadata.Items, fact.Effect)
		}
	}
	coverageInput := struct {
		Mode       string                  `json:"mode"`
		Factory    string                  `json:"factory"`
		Repository string                  `json:"repository_mode"`
		Candidates []jobAdmissionCandidate `json:"candidates"`
	}{"admission", "transparent_inference", "factory_reconciled", candidates}
	checked, err := handler.core.batch(ctx, []any{inferenceOperation{"configuration_coverage", coverageInput}})
	if err != nil {
		return inferencePrepared{}, err
	}
	var decisions struct {
		Kind       string                 `json:"kind"`
		Mode       string                 `json:"mode"`
		Candidates []jobAdmissionDecision `json:"candidates"`
	}
	if json.Unmarshal(checked[0], &decisions) != nil || decisions.Kind != "configuration_coverage" || decisions.Mode != "admission" || len(decisions.Candidates) != len(candidates) {
		return inferencePrepared{}, errors.New("invalid native fixed inference admission")
	}
	// 原固定入口逐侧执行validator：攻击方失败时不继续返回防守方的另一组失败。
	for _, side := range sides {
		if failures := admissionFailures([]jobSideFacts{side}, decisions.Candidates); len(failures) > 0 {
			parts := make([]string, 0, len(failures))
			for _, failure := range failures {
				parts = append(parts, failure.Source+":"+failure.Requested+":"+failure.Status+":missing="+strings.Join(failure.Missing, ","))
			}
			return inferencePrepared{}, &inferenceRequestError{status: 422, code: "fixed_battle_mechanism_rejected",
				message: "strict mechanism admission rejected: " + strings.Join(parts, "; "), failures: failures}
		}
	}
	sorted, err := handler.fixedMoveIDs(ctx, selections, sides, facts)
	if err != nil {
		return inferencePrepared{}, err
	}
	profiles, failed := jobProfiles(selections)
	if failed != nil {
		return inferencePrepared{}, inferenceInvalid(strings.TrimPrefix(failed.Diagnostic, "ConfigurationSpaceError: "))
	}
	request := jobSubmissionRequest{jobPoolCommand: jobPoolCommand{Ruleset: input.Ruleset, Version: input.Version,
		Attacker: selections[0], Defender: selections[1], AttackerPolicy: inferencePolicy(input.AttackerPolicy), DefenderPolicy: inferencePolicy(input.DefenderPolicy)},
		Execution: jobExecutionBudget{MaxNodes: input.Limits.Nodes, MaxEdges: input.Limits.Edges, MaxTurns: &input.Limits.Turns}}
	template, err := (jobSubmissionHandler{core: handler.core}).template(ctx, request, snapshot, sides, profiles)
	if err != nil {
		return inferencePrepared{}, err
	}
	encoded, err := nativeworker.ProjectFixedBattleTemplate(template, jobs.CaseDefinition{AttackerMoves: sorted[0], DefenderMoves: sorted[1]})
	if err != nil {
		return inferencePrepared{}, err
	}
	var batch struct {
		Operations []json.RawMessage `json:"operations"`
	}
	if json.Unmarshal(encoded, &batch) != nil || len(batch.Operations) != 1 {
		return inferencePrepared{}, errors.New("invalid projected fixed battle request")
	}
	var operation struct {
		State struct {
			Attacker inferenceNativeBattler `json:"attacker"`
			Defender inferenceNativeBattler `json:"defender"`
		} `json:"state"`
	}
	if err := json.Unmarshal(batch.Operations[0], &operation); err != nil {
		return inferencePrepared{}, err
	}
	return inferencePrepared{batch.Operations[0], metadata, inferencePokemon(operation.State.Attacker, input.Attacker.Profile), inferencePokemon(operation.State.Defender, input.Defender.Profile)}, nil
}

// fixedMoveIDs 调用唯一Core组合器取得原provider的规范ID顺序；Go不排序、枚举或合并技能。
// selections/sides/facts均来自当前独立快照，返回两侧完整唯一技能组或整体错误。
func (handler fixedInferenceHandler) fixedMoveIDs(ctx context.Context, selections []jobSelection, sides []jobSideFacts, facts []jobAdmissionFact) ([][]int, error) {
	operations := make([]any, 0, 2)
	for index, selection := range selections {
		input := inferenceMoveInput{Candidates: []inferenceMoveCandidate{}, Requested: selection.Moves, Slots: []int{len(selection.Moves)}, Maximum: 1}
		for _, selected := range sides[index].moves {
			fact := facts[selected.index]
			input.Candidates = append(input.Candidates, inferenceMoveCandidate{*fact.MoveID, strconv.Itoa(*fact.MoveID), fact.Move, fact.Effect, "supported", fact.RepositoryReason})
		}
		operations = append(operations, inferenceOperation{"configuration_moves", input})
	}
	results, err := handler.core.batch(ctx, operations)
	if err != nil {
		return nil, err
	}
	ids := make([][]int, 2)
	for index, raw := range results {
		var value struct {
			Kind    string `json:"kind"`
			Count   string `json:"raw_combination_count"`
			Classes []struct {
				Moves []struct {
					Spec jobMoveSpec `json:"spec"`
				} `json:"moves"`
			} `json:"classes"`
		}
		if json.Unmarshal(raw, &value) != nil || value.Kind != "configuration_moves" || value.Count != "1" || len(value.Classes) != 1 || len(value.Classes[0].Moves) != len(selections[index].Moves) {
			return nil, errors.New("fixed command did not resolve to one native move class")
		}
		ids[index] = make([]int, 0, len(value.Classes[0].Moves))
		for _, move := range value.Classes[0].Moves {
			ids[index] = append(ids[index], move.Spec.MoveID)
		}
	}
	return ids, nil
}

// inferencePokemon 只投影已计算的原生初始配置；profileKey只生成原provider解释标签。
func inferencePokemon(value inferenceNativeBattler, profileKey string) inferencePokemonSummary {
	ids, names, labels := []int{}, []string{}, []string{}
	for _, move := range value.Spec.Moves {
		ids = append(ids, move.MoveID)
		names = append(names, move.Name)
		labels = append(labels, strconv.Itoa(move.MoveID))
	}
	pokemon := value.Spec.Pokemon
	return inferencePokemonSummary{value.Spec.ID, value.Spec.Name, pokemon.Level, pokemon.Ability, pokemon.Item, ids, names, pokemon.Stats,
		map[string]string{"moves": strings.Join(labels, ","), "stats": "preset:" + profileKey, "ability": pokemon.Ability, "item": pokemon.Item}}
}

// solve 在同一原子Core批次读取完整机制集合并求解固定战斗，最后才组装旧HTTP摘要。
// ctx控制child生命周期；prepared只读，任何未知/截断都返回明确失败而不是零概率。
func (handler fixedInferenceHandler) solve(ctx context.Context, input inferenceFixedRequest, prepared inferencePrepared) (inferenceSummary, error) {
	results, err := handler.core.batch(ctx, []any{inferenceOperation{"configuration_coverage", prepared.metadata}, prepared.operation})
	if err != nil {
		return inferenceSummary{}, err
	}
	var metadata struct {
		Kind     string   `json:"kind"`
		Mode     string   `json:"mode"`
		Included []string `json:"included_mechanisms"`
		Excluded []string `json:"excluded_mechanisms"`
	}
	var result inferenceNativeResult
	if json.Unmarshal(results[0], &metadata) != nil || metadata.Kind != "configuration_coverage" || metadata.Mode != "describe" || metadata.Included == nil || metadata.Excluded == nil ||
		json.Unmarshal(results[1], &result) != nil || result.Kind != "fixed_battle" || result.Observer != "attacker" || result.Statistics.Nodes < 1 {
		return inferenceSummary{}, errors.New("invalid native fixed inference response")
	}
	if result.Status != "solved" {
		diagnostics := result.Diagnostics
		if result.Status == "incomplete-graph" {
			diagnostics = []string{}
			for _, reason := range result.Truncations {
				diagnostics = append(diagnostics, "graph truncated: "+reason)
			}
			if len(diagnostics) == 0 {
				diagnostics = append(diagnostics, "graph contains unknown nodes")
			}
		}
		if len(diagnostics) == 0 {
			diagnostics = []string{result.Status}
		}
		return inferenceSummary{}, &inferenceRequestError{status: 422, code: "fixed_battle_not_completely_solved", message: "battle graph was not completely solved: " + strings.Join(diagnostics, "; ")}
	}
	win, err := inferenceDisplayProbability(result.Win)
	if err != nil {
		return inferenceSummary{}, err
	}
	loss, err := inferenceDisplayProbability(result.Loss)
	if err != nil {
		return inferenceSummary{}, err
	}
	draw, err := inferenceDisplayProbability(result.Draw)
	if err != nil {
		return inferenceSummary{}, err
	}
	expected, err := inferenceDisplayExpected(result.Expected.Status, result.Expected.Value)
	if err != nil {
		return inferenceSummary{}, err
	}
	warnings := []string{}
	for _, excluded := range metadata.Excluded {
		warnings = append(warnings, "未纳入机制："+excluded)
	}
	warnings = append(warnings, result.Diagnostics...)
	truncations, diagnostics := result.Truncations, result.Diagnostics
	if truncations == nil {
		truncations = []string{}
	}
	if diagnostics == nil {
		diagnostics = []string{}
	}
	stats := result.Statistics
	return inferenceSummary{input.Ruleset, input.Version, "attacker", prepared.attacker, prepared.defender, win, loss, draw, expected,
		inferencePolicy(input.AttackerPolicy), inferencePolicy(input.DefenderPolicy),
		inferenceGraphSummary{stats.Nodes, stats.Edges, stats.MaxTurn, stats.Closed, stats.ReachableCycle, len(truncations) == 0, truncations},
		[]json.RawMessage{}, metadata.Included, metadata.Excluded, 100,
		inferenceCompleteness{len(truncations) == 0, result.Status, truncations, diagnostics, warnings}}, nil
}
