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

// registerFixedInference 挂接原summary和共享图族路由；mux与db由调用方拥有，不启动后台生命周期。
func registerFixedInference(mux *http.ServeMux, db *sql.DB) {
	handler := fixedInferenceHandler{catalog.New(db), calculatorHandler{worker: configuredWorker()}}
	mux.HandleFunc("POST /v1/inference/fixed-one-on-one", handler.summary)
	registerFixedSnapshotRoute(mux, handler)
	store := registerFixedGraphRoutes(mux, handler)
	registerConfigurationCaseGraph(mux, db, handler, store)
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
	return handler.prepareContext(ctx, input, jobExecutionBudget{MaxNodes: input.Limits.Nodes, MaxEdges: input.Limits.Edges, MaxTurns: &input.Limits.Turns}, inferencePreparationStrict)
}

// inferencePreparationMode 明确区分原公开fixed严格入口与原普通reference生成器，不能按特性名单分支。
type inferencePreparationMode uint8

const (
	inferencePreparationStrict inferencePreparationMode = iota
	inferencePreparationReference
)

// prepareReference 使用原普通provider/reconciler，budget来自原入口/任务执行spec且保留nil回合保护。
// input完整选择仍只读；返回同一PG快照的完整准备，不在Go决定partial机制是否可执行。
func (handler fixedInferenceHandler) prepareReference(ctx context.Context, input inferenceFixedRequest, budget jobExecutionBudget) (inferencePrepared, error) {
	return handler.prepareContext(ctx, input, budget, inferencePreparationReference)
}

// prepareContext 只选择原入口composition；PG读取、Coreprovider、状态模板共享唯一实现。
// budget是入口拥有的原预算，不套同步schema的较窄范围；mode不改变Core数学或玩家选择策略。
func (handler fixedInferenceHandler) prepareContext(ctx context.Context, input inferenceFixedRequest, budget jobExecutionBudget, mode inferencePreparationMode) (inferencePrepared, error) {
	if mode == inferencePreparationStrict && input.Ruleset != "pokemon-champion" {
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
	if mode == inferencePreparationReference {
		// 原入口先检查同一repository受控道具集合，再准备profile/provider；这里只做资料身份匹配。
		for _, selection := range selections {
			requested := "none"
			if selection.Fixed.Item != nil && *selection.Fixed.Item != "" {
				requested = *selection.Fixed.Item
			}
			allowed := false
			for _, candidate := range snapshot.Items {
				if candidate.Identifier == requested {
					allowed = true
					break
				}
			}
			if !allowed {
				return inferencePrepared{}, inferenceInvalid("item " + pythonRepr(requested) + " is not available in the controlled item boundary")
			}
		}
	}
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
	if mode == inferencePreparationStrict {
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
	}
	profiles, failed := jobProfiles(selections)
	if failed != nil {
		return inferencePrepared{}, inferenceInvalid(strings.TrimPrefix(failed.Diagnostic, "ConfigurationSpaceError: "))
	}
	// 严格准入之后仍须经过原四维provider；例如显式"none"与null道具由原item provider独立解释。
	sorted, err := handler.referenceMoveIDs(ctx, input, selections, snapshot, profiles)
	if err != nil {
		return inferencePrepared{}, err
	}
	request := jobSubmissionRequest{jobPoolCommand: jobPoolCommand{Ruleset: input.Ruleset, Version: input.Version,
		Attacker: selections[0], Defender: selections[1], AttackerPolicy: inferencePolicy(input.AttackerPolicy), DefenderPolicy: inferencePolicy(input.DefenderPolicy)},
		Execution: budget}
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
	if mode == inferencePreparationReference {
		batch.Operations[0], err = withTransparentInferenceContext(batch.Operations[0])
		if err != nil {
			return inferencePrepared{}, err
		}
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

// inferenceComputation 持有同一Core调用的摘要和原始图结果，图创建不再重复求解。
type inferenceComputation struct {
	summary       inferenceSummary
	native        inferenceNativeResult
	engineVersion string
	rulesVersion  string
}

// solve 保留原summary入口签名；ctx取消传播到唯一Core调用，只返回完整摘要或原错误。
func (handler fixedInferenceHandler) solve(ctx context.Context, input inferenceFixedRequest, prepared inferencePrepared) (inferenceSummary, error) {
	// 原fixed_battle_workflow的summary入口实际使用SummaryStateGraphBuilder，独立于图浏览Full模式。
	var operation map[string]json.RawMessage
	if json.Unmarshal(prepared.operation, &operation) != nil {
		return inferenceSummary{}, errors.New("invalid prepared summary request")
	}
	operation["graph_mode"] = json.RawMessage(`"configuration_summary"`)
	encoded, err := json.Marshal(operation)
	if err != nil {
		return inferenceSummary{}, err
	}
	prepared.operation = encoded
	result, err := handler.calculate(ctx, input, prepared)
	return result.summary, err
}

// calculate 在同一原子Core批次读取机制并求解固定战斗，保留同一次结果的完整图供原graph入口使用。
// ctx控制child生命周期；prepared只读，任何未知/截断都返回明确失败而不是零概率。
func (handler fixedInferenceHandler) calculate(ctx context.Context, input inferenceFixedRequest, prepared inferencePrepared) (inferenceComputation, error) {
	envelope, err := handler.core.batchEnvelope(ctx, []any{inferenceOperation{"configuration_coverage", prepared.metadata}, prepared.operation})
	if err != nil {
		return inferenceComputation{}, err
	}
	results := envelope.Results
	var metadata struct {
		Kind     string   `json:"kind"`
		Mode     string   `json:"mode"`
		Included []string `json:"included_mechanisms"`
		Excluded []string `json:"excluded_mechanisms"`
	}
	var result inferenceNativeResult
	if json.Unmarshal(results[0], &metadata) != nil || metadata.Kind != "configuration_coverage" || metadata.Mode != "describe" || metadata.Included == nil || metadata.Excluded == nil ||
		json.Unmarshal(results[1], &result) != nil || result.Kind != "fixed_battle" || result.Observer != "attacker" || result.Statistics.Nodes < 1 {
		return inferenceComputation{}, errors.New("invalid native fixed inference response")
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
		return inferenceComputation{}, &inferenceRequestError{status: 422, code: "fixed_battle_not_completely_solved", message: "battle graph was not completely solved: " + strings.Join(diagnostics, "; ")}
	}
	win, err := inferenceDisplayProbability(result.Win)
	if err != nil {
		return inferenceComputation{}, err
	}
	loss, err := inferenceDisplayProbability(result.Loss)
	if err != nil {
		return inferenceComputation{}, err
	}
	draw, err := inferenceDisplayProbability(result.Draw)
	if err != nil {
		return inferenceComputation{}, err
	}
	expected, err := inferenceDisplayExpected(result.Expected.Status, result.Expected.Value)
	if err != nil {
		return inferenceComputation{}, err
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
	return inferenceComputation{inferenceSummary{input.Ruleset, input.Version, "attacker", prepared.attacker, prepared.defender, win, loss, draw, expected,
		inferencePolicy(input.AttackerPolicy), inferencePolicy(input.DefenderPolicy),
		inferenceGraphSummary{stats.Nodes, stats.Edges, stats.MaxTurn, stats.Closed, stats.ReachableCycle, len(truncations) == 0, truncations},
		[]json.RawMessage{}, metadata.Included, metadata.Excluded, 100,
		inferenceCompleteness{len(truncations) == 0, result.Status, truncations, diagnostics, warnings}}, result, envelope.EngineVersion, envelope.RulesVersion}, nil
}
