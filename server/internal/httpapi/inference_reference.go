package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"pokemonbattleinference/server/internal/catalog"
	"strconv"
)

// inferenceReferenceAbility 只传原合法特性与repository状态，Core拥有透明工厂及promotion决定。
type inferenceReferenceAbility struct {
	ID      string `json:"identifier"`
	Support string `json:"support"`
	Reason  string `json:"reason"`
}

// inferenceReferenceSide 保留原四维单一选择与全部合法候选，不能在Go按机制名单过滤。
type inferenceReferenceSide struct {
	Ruleset    string                      `json:"ruleset_id"`
	Version    int                         `json:"version_group_id"`
	ID         int                         `json:"pokemon_id"`
	Name       string                      `json:"name"`
	Types      []int                       `json:"types"`
	CanEvolve  bool                        `json:"can_evolve"`
	Moves      inferenceMoveInput          `json:"moves"`
	Stats      json.RawMessage             `json:"stats"`
	Abilities  []inferenceReferenceAbility `json:"abilities"`
	Requested  []string                    `json:"requested_abilities"`
	Items      []*string                   `json:"items"`
	Maximum    int                         `json:"max_raw_configurations"`
	Factory    string                      `json:"factory"`
	Repository string                      `json:"repository_mode"`
}

// inferenceReferenceSpaceInput 每侧真正固定四维，Core返回完整选择与原1/1覆盖，不预组合招式。
type inferenceReferenceSpaceInput struct {
	Attacker   inferenceReferenceSide `json:"attacker"`
	Defender   inferenceReferenceSide `json:"defender"`
	Assumption string                 `json:"weight_assumption"`
	Maximum    int                    `json:"max_raw_pairs"`
}

// referenceSide 机械组装同一PG不可变快照；能力profile复用现有Core输入适配，不计算实际能力。
// selection是原用户选择，pokemon包含全部合法候选，返回值不提升/删除任何repository状态。
func referenceSide(input inferenceFixedRequest, selection jobSelection, pokemon catalog.InferencePokemon, profile calculatorProfile) (inferenceReferenceSide, error) {
	result := inferenceReferenceSide{Ruleset: input.Ruleset, Version: input.Version, ID: pokemon.ID, Name: pokemon.Identifier,
		Types: []int{}, CanEvolve: pokemon.CanEvolve, Moves: inferenceMoveInput{Candidates: []inferenceMoveCandidate{}, Requested: selection.Moves, Slots: []int{len(selection.Moves)}, Maximum: 1},
		Abilities: []inferenceReferenceAbility{}, Requested: []string{selection.Fixed.Ability}, Items: []*string{selection.Fixed.Item}, Maximum: 1, Factory: "transparent_inference", Repository: "factory_reconciled"}
	for _, entry := range pokemon.Types {
		result.Types = append(result.Types, entry.ID)
	}
	for _, move := range pokemon.Moves {
		result.Moves.Candidates = append(result.Moves.Candidates, inferenceMoveCandidate{move.ID, strconv.Itoa(move.ID), nativeJobMove(move), move.Effect, move.Capability.Status, move.Capability.Reason})
	}
	for _, ability := range pokemon.Abilities {
		result.Abilities = append(result.Abilities, inferenceReferenceAbility{ability.Effect, ability.Capability.Status, ability.Capability.Reason})
	}
	raw, err := json.Marshal(solverStatsOperation(pokemon.Base, profile, selection.Fixed.Level))
	if err != nil {
		return inferenceReferenceSide{}, err
	}
	var operation struct {
		Input json.RawMessage `json:"input"`
	}
	if json.Unmarshal(raw, &operation) != nil || len(operation.Input) == 0 {
		return inferenceReferenceSide{}, errors.New("invalid native reference stat input")
	}
	result.Stats = operation.Input
	return result, nil
}

// referenceMoveIDs 调用同一Core provider/reconciler，接收真正固定代表的技能身份，不复刻选择或枚举规则。
// ctx贯穿独立child，snapshot/profiles只读；空维度保原Core业务诊断而非伪造中性特性继续执行。
func (handler fixedInferenceHandler) referenceMoveIDs(ctx context.Context, input inferenceFixedRequest, selections []jobSelection, snapshot catalog.InferenceSnapshot, profiles []calculatorProfile) ([][]int, error) {
	if len(selections) != 2 || len(snapshot.Pokemon) != 2 || len(profiles) != 2 {
		return nil, errors.New("reference preparation requires two complete sides")
	}
	first, err := referenceSide(input, selections[0], snapshot.Pokemon[0], profiles[0])
	if err != nil {
		return nil, err
	}
	second, err := referenceSide(input, selections[1], snapshot.Pokemon[1], profiles[1])
	if err != nil {
		return nil, err
	}
	raw, err := executeBusinessCoreOperation(ctx, handler.core, inferenceOperation{"configuration_space", inferenceReferenceSpaceInput{first, second, "uniform_raw_configuration", 1}})
	if err != nil {
		var rejection *nativeBusinessRejection
		if errors.As(err, &rejection) {
			return nil, inferenceInvalid(rejection.message)
		}
		return nil, err
	}
	// 此处仅读取Core固定代表；完整canonical/job身份与配置权重仍由原独立操作拥有。
	type side struct {
		Count   string `json:"raw_configuration_count"`
		Classes []struct {
			Moves struct {
				Moves []struct {
					Spec jobMoveSpec `json:"spec"`
				} `json:"moves"`
			} `json:"moves"`
		} `json:"classes"`
	}
	var result struct {
		Kind     string `json:"kind"`
		Count    string `json:"raw_pair_count"`
		Attacker side   `json:"attacker"`
		Defender side   `json:"defender"`
	}
	if json.Unmarshal(raw, &result) != nil || result.Kind != "configuration_space" || result.Count != "1" {
		return nil, errors.New("invalid native reference configuration space")
	}
	selected := make([][]int, 0, 2)
	for _, value := range []side{result.Attacker, result.Defender} {
		if value.Count != "1" || len(value.Classes) != 1 || len(value.Classes[0].Moves.Moves) == 0 {
			return nil, errors.New("reference command did not resolve to one native configuration")
		}
		ids := make([]int, 0, len(value.Classes[0].Moves.Moves))
		for _, move := range value.Classes[0].Moves.Moves {
			ids = append(ids, move.Spec.MoveID)
		}
		selected = append(selected, ids)
	}
	return selected, nil
}

// withTransparentInferenceContext 只选择原入口的明确composition，不根据任何机制名称改写能力标识。
// raw必须是已准备的完整fixed操作；返回独立拥有字节，两侧白名单/UNKNOWN等价与执行由Core判定。
func withTransparentInferenceContext(raw json.RawMessage) (json.RawMessage, error) {
	var operation map[string]json.RawMessage
	if json.Unmarshal(raw, &operation) != nil {
		return nil, errors.New("invalid reference fixed request")
	}
	var state map[string]json.RawMessage
	if json.Unmarshal(operation["state"], &state) != nil {
		return nil, errors.New("invalid reference initial state")
	}
	for _, side := range []string{"attacker", "defender"} {
		var battler map[string]json.RawMessage
		if json.Unmarshal(state[side], &battler) != nil {
			return nil, errors.New("invalid reference initial battler")
		}
		var spec map[string]json.RawMessage
		if json.Unmarshal(battler["spec"], &spec) != nil {
			return nil, errors.New("invalid reference Pokemon specification")
		}
		spec["ability_context"] = json.RawMessage(`"transparent_inference"`)
		encoded, err := json.Marshal(spec)
		if err != nil {
			return nil, err
		}
		battler["spec"] = encoded
		encoded, err = json.Marshal(battler)
		if err != nil {
			return nil, err
		}
		state[side] = encoded
	}
	encoded, err := json.Marshal(state)
	if err != nil {
		return nil, err
	}
	operation["state"] = encoded
	return json.Marshal(operation)
}
