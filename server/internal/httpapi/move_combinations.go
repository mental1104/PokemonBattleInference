package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"pokemonbattleinference/server/internal/catalog"
	"sort"
	"strconv"
	"strings"
	"time"
)

// moveCombinationSide 保留原组合预览一侧事实；省略level默认为50，不要求解析stat profile。
type moveCombinationSide struct {
	jobFixed
	Moves []int `json:"candidate_move_ids"`
}

// UnmarshalJSON 仅处理原默认level；data借用一次，显式null层级在HTTPschema阶段拒绝。
func (side *moveCombinationSide) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("combination side must be an object")
	}
	type plain moveCombinationSide
	value := plain{jobFixed: jobFixed{Level: 50}}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	if string(fields["level"]) == "null" {
		return errors.New("level must be an integer")
	}
	*side = moveCombinationSide(value)
	return nil
}

// moveCombinationRequest 是原只枚举HTTP合同，不包含solver或任务执行预算。
type moveCombinationRequest struct {
	Ruleset  string               `json:"ruleset_id"`
	Version  int                  `json:"version_group_id"`
	Revision string               `json:"calculation_revision"`
	Attacker *moveCombinationSide `json:"attacker"`
	Defender *moveCombinationSide `json:"defender"`
}

// moveSetOption 只投影Core已枚举的有序move IDs，名字来自同一冻结知识快照。
type moveSetOption struct {
	ID    string   `json:"move_set_id"`
	IDs   []int    `json:"move_ids"`
	Names []string `json:"move_names"`
}

// moveSetSideResponse 是旧一侧列表合同；计数来自Core，不在Go计算组合数。
type moveSetSideResponse struct {
	ID         int             `json:"pokemon_id"`
	Name       string          `json:"pokemon_name"`
	Candidates int             `json:"candidate_count"`
	Count      int             `json:"move_set_count"`
	Sets       []moveSetOption `json:"move_sets"`
}

// moveCombinationHandler 共享真实知识和Core编排，但从不创建任务或调用战斗solver。
type moveCombinationHandler struct {
	catalog *catalog.Store
	core    calculatorHandler
}

// registerMoveCombinations 挂接旧组合预览路由；db只用于RR读取，不发生业务表写入。
func registerMoveCombinations(mux *http.ServeMux, db *sql.DB) {
	mux.Handle("POST /v1/inference/move-set-combinations", moveCombinationHandler{catalog.New(db), calculatorHandler{worker: configuredWorker()}})
}

// ServeHTTP 冻结两侧知识后按原顺序检查revision/能力/道具/招式，再交Core唯一组合器。
// r取消和30秒截止传播到PG/子进程；w只返回完整两侧列表或原稳定拒绝。
func (handler moveCombinationHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	input := moveCombinationRequest{Ruleset: "pokemon-champion", Version: 25}
	if !decodeJSON(w, r, &input) {
		return
	}
	if input.Attacker == nil || input.Defender == nil || input.Revision == "" {
		detail(w, 422, "both sides and calculation_revision are required")
		return
	}
	for _, side := range []*moveCombinationSide{input.Attacker, input.Defender} {
		if side.PokemonID <= 0 || side.Level < 1 || side.Level > 100 || side.Profile == "" || side.Ability == "" || len(side.Moves) < 1 || len(side.Moves) > 10 {
			detail(w, 422, "invalid combination side")
			return
		}
		chosen := inferenceChosenSide{jobFixed: side.jobFixed, Moves: []int{1}}
		if err := chosen.validate(); err != nil {
			inferenceFailure(w, inferenceInvalid(err.Error()))
			return
		}
		sort.Ints(side.Moves)
	}
	if input.Attacker.Level != input.Defender.Level {
		inferenceFailure(w, inferenceInvalid("both sides must use the same level in v1"))
		return
	}
	if input.Ruleset != "pokemon-champion" {
		inferenceFailure(w, inferenceInvalid("effect factory ruleset does not match candidate command"))
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	snapshot, err := handler.catalog.Inference(ctx, input.Ruleset, input.Version, []int{input.Attacker.PokemonID, input.Defender.PokemonID})
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
	if input.Revision != "battle-inference.summary-exploration.v2" {
		inferenceFailure(w, inferenceInvalid("candidate pool calculation_revision does not match the request"))
		return
	}
	selections := []jobSelection{{input.Attacker.jobFixed, input.Attacker.Moves}, {input.Defender.jobFixed, input.Defender.Moves}}
	facts := []jobAdmissionFact{}
	sides := make([]jobSideFacts, 2)
	for index, selection := range selections {
		sides[index], err = appendJobFacts(&facts, selection, snapshot.Pokemon[index], snapshot.Items, input.Version, index)
		if err != nil {
			calculatorFailure(w, err)
			return
		}
	}
	candidates := make([]jobAdmissionCandidate, 0, len(facts))
	for _, fact := range facts {
		candidates = append(candidates, fact.jobAdmissionCandidate)
	}
	checked, err := handler.core.batch(ctx, []any{inferenceOperation{"configuration_coverage", struct {
		Mode       string                  `json:"mode"`
		Factory    string                  `json:"factory"`
		Repository string                  `json:"repository_mode"`
		Candidates []jobAdmissionCandidate `json:"candidates"`
	}{"admission", "transparent_inference", "factory_reconciled", candidates}}})
	if err != nil {
		calculatorFailure(w, err)
		return
	}
	var decisions struct {
		Kind       string                 `json:"kind"`
		Candidates []jobAdmissionDecision `json:"candidates"`
	}
	if json.Unmarshal(checked[0], &decisions) != nil || decisions.Kind != "configuration_coverage" || len(decisions.Candidates) != len(facts) {
		detail(w, 503, "invalid native admission result")
		return
	}
	// 原组合用例先查双方固定机制，再查双方招式；不使用job的四招分块失败envelope。
	for index, side := range sides {
		for _, selected := range []struct {
			Fact       selectedJobFact
			Source     string
			Identifier string
		}{{side.ability, "ability", selections[index].Fixed.Ability}, {side.item, "item", "none"}} {
			identifier := selected.Identifier
			if selected.Source == "item" && selections[index].Fixed.Item != nil {
				identifier = *selections[index].Fixed.Item
			}
			if selected.Fact.missing != nil || selected.Fact.index < 0 || !decisions.Candidates[selected.Fact.index].Selectable {
				inferenceFailure(w, inferenceInvalid(fmt.Sprintf("%s '%s' is not selectable for Pokemon %d", selected.Source, identifier, selections[index].Fixed.PokemonID)))
				return
			}
		}
	}
	for _, side := range sides {
		// 原MoveCandidatePool在固定机制全部通过之后才规范化/拒绝重复；保留多重非法输入的错误优先级。
		seen := map[string]bool{}
		for _, move := range side.moves {
			id, parseErr := strconv.Atoi(move.requested)
			if parseErr != nil || id <= 0 {
				inferenceFailure(w, inferenceInvalid("candidate move ids must be positive integers"))
				return
			}
			if seen[move.requested] {
				inferenceFailure(w, inferenceInvalid("candidate move ids must be unique"))
				return
			}
			seen[move.requested] = true
		}
		rejected := []string{}
		for _, move := range side.moves {
			if move.missing != nil {
				rejected = append(rejected, move.requested+":not-legal")
			} else if decision := decisions.Candidates[move.index]; !decision.Selectable {
				rejected = append(rejected, move.requested+":"+decision.Status+":"+decision.Reason)
			}
		}
		if len(rejected) > 0 {
			inferenceFailure(w, inferenceInvalid("move selection rejected: "+strings.Join(rejected, "; ")))
			return
		}
	}
	outputs, err := handler.enumerate(ctx, input, snapshot, selections, sides, facts)
	if err != nil {
		calculatorFailure(w, err)
		return
	}
	writeJSON(w, 200, outputs)
}

// enumerate 将已严格准入的唯一ID池交两次Core moves和一次job空页；不在Go生成笛卡尔积。
// snapshot/selections/sides/facts同源且不可变；返回原公开DTO，任何Core缺页/数量不一致整体失败。
func (handler moveCombinationHandler) enumerate(ctx context.Context, input moveCombinationRequest, snapshot catalog.InferenceSnapshot, selections []jobSelection, sides []jobSideFacts, facts []jobAdmissionFact) (any, error) {
	operations := []any{}
	for index, selection := range selections {
		moves := inferenceMoveInput{Candidates: []inferenceMoveCandidate{}, Requested: selection.Moves, Slots: []int{}, Maximum: 10000}
		for _, chosen := range sides[index].moves {
			fact := facts[chosen.index]
			moves.Candidates = append(moves.Candidates, inferenceMoveCandidate{*fact.MoveID, strconv.Itoa(*fact.MoveID), fact.Move, fact.Effect, "supported", fact.RepositoryReason})
		}
		operations = append(operations, inferenceOperation{"configuration_moves", moves})
	}
	fixed := inferenceFixedRequest{Ruleset: input.Ruleset, Version: input.Version, Attacker: &inferenceChosenSide{jobFixed: selections[0].Fixed, Moves: selections[0].Moves}, Defender: &inferenceChosenSide{jobFixed: selections[1].Fixed, Moves: selections[1].Moves}, AttackerPolicy: "uniform-random", DefenderPolicy: "uniform-random", Limits: defaultInferenceLimits()}
	command := fixedSubmissionRequest(fixed).jobPoolCommand
	operations = append(operations, inferenceOperation{"job_move_pool", struct {
		Command   jobPoolCommand       `json:"command"`
		Admission jobAdmissionSnapshot `json:"admission"`
		Offset    int                  `json:"offset"`
		Limit     int                  `json:"limit"`
	}{command, jobAdmissionSnapshot{Ruleset: input.Ruleset, Version: input.Version, Revision: input.Revision, Candidates: facts}, 0, 0}})
	results, err := handler.core.batch(ctx, operations)
	if err != nil {
		return nil, err
	}
	var count jobPoolPage
	if json.Unmarshal(results[2], &count) != nil || count.Kind != "job_move_pool" {
		return nil, errors.New("invalid native combination count")
	}
	output := make([]moveSetSideResponse, 2)
	for index, raw := range results[:2] {
		var native struct {
			Kind    string `json:"kind"`
			Classes []struct {
				Moves []struct {
					Spec jobMoveSpec `json:"spec"`
				} `json:"moves"`
			} `json:"classes"`
		}
		if json.Unmarshal(raw, &native) != nil || native.Kind != "configuration_moves" {
			return nil, errors.New("invalid native move combinations")
		}
		pokemon := snapshot.Pokemon[index]
		sets := make([]moveSetOption, 0, len(native.Classes))
		for _, class := range native.Classes {
			ids := []int{}
			names := []string{}
			labels := []string{}
			for _, move := range class.Moves {
				ids = append(ids, move.Spec.MoveID)
				names = append(names, move.Spec.Name)
				labels = append(labels, strconv.Itoa(move.Spec.MoveID))
			}
			sets = append(sets, moveSetOption{"move-set:" + strings.Join(labels, ","), ids, names})
		}
		output[index] = moveSetSideResponse{pokemon.ID, pokemon.Name, len(selections[index].Moves), len(sets), sets}
	}
	return struct {
		Ruleset  string              `json:"ruleset_id"`
		Version  int                 `json:"version_group_id"`
		Revision string              `json:"calculation_revision"`
		Attacker moveSetSideResponse `json:"attacker"`
		Defender moveSetSideResponse `json:"defender"`
		Count    int                 `json:"configuration_pair_count"`
	}{input.Ruleset, input.Version, input.Revision, output[0], output[1], count.CaseCount}, nil
}
