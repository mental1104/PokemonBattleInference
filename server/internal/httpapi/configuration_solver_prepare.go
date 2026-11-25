package httpapi

import (
	"context"
	"encoding/json"
	"fmt"
	"pokemonbattleinference/server/internal/catalog"
	"pokemonbattleinference/server/internal/configurations"
	"strings"
)

// solverPokemonNative 是原静态目标上下文，不携带动态HP/grounding/can_evolve，交Core保留原静态计算语义。
type solverPokemonNative struct {
	Level   int                   `json:"level"`
	Types   []int                 `json:"types"`
	Stats   configurations.Spread `json:"stats"`
	Ability string                `json:"ability"`
	Item    string                `json:"item"`
}

// solverTemplateNative 保存原模板事实，五轴性格不改成平衡25性格；所有能力计算由Core处理。
type solverTemplateNative struct {
	Key    string    `json:"preset_key"`
	IVs    [6]int    `json:"ivs"`
	EVs    [6]int    `json:"evs"`
	Nature []float64 `json:"nature"`
}

// solverPrepared 保存同一次知识快照及Core准备的目标/模板事实；metadata只用于原HTTP展示。
type solverPrepared struct {
	Snapshot  catalog.GoalSnapshot
	Operation map[string]any
	Profiles  map[string]calculatorProfile
	Warnings  []string
}

// solverAbility 校验当前合法特性，返回原静态效果标识/可选warning；角色由原目标类型明确决定。
func solverAbility(pokemon catalog.GoalPokemon, identifier, role, label string) (string, string, error) {
	normalized := strings.TrimSpace(identifier)
	for _, ability := range pokemon.Abilities {
		if ability.Identifier != normalized {
			continue
		}
		if !ability.Implemented {
			return "none", fmt.Sprintf("%s特性“%s”尚未实现，本次按无特性处理。", label, ability.DisplayName), nil
		}
		return strings.ReplaceAll(normalized, "-", "_"), "", nil
	}
	return "", "", &catalog.CalculationInputError{Message: fmt.Sprintf("ability is not available for %s in this ruleset: %s", role, normalized)}
}

// solverItem 复用原别名边界，但错误文本保留目标求解器的strip后标识；不求道具倍率。
func solverItem(identifier *string) (string, error) {
	if identifier == nil {
		return "none", nil
	}
	value := strings.TrimSpace(*identifier)
	item, err := calculatorItem(&value)
	if err != nil {
		return "", &catalog.CalculationInputError{Message: "unsupported item_identifier: " + value}
	}
	return item, nil
}

// solverStatsOperation 只把profile的六EV/IV和五轴倍率送Core，不自行派生实际能力。
func solverStatsOperation(base configurations.Spread, profile calculatorProfile, level int) any {
	nature := make([]float64, 5)
	for axis := range nature {
		nature[axis] = float64(profile.Nature[axis+1]) / 10
	}
	return map[string]any{"kind": "configuration_stats", "input": map[string]any{"base": base, "level": level, "enumeration": map[string]any{"mode": "preset", "presets": []any{map[string]any{"label": profile.View.Label, "profile": map[string]any{"ivs": profile.IVs, "evs": profile.EVs, "nature": nature}}}}, "max_raw_profiles": 1}}
}

// solverTemplateFact 只投影原模板EV/IV/nature事实；没有搜索/筛选/去重或能力数学。
func solverTemplateFact(key string, profile calculatorProfile) solverTemplateNative {
	nature := make([]float64, 5)
	for axis := range nature {
		nature[axis] = float64(profile.Nature[axis+1]) / 10
	}
	ivs := [6]int{profile.IVs.HP, profile.IVs.Attack, profile.IVs.Defense, profile.IVs.SpecialAttack, profile.IVs.SpecialDefense, profile.IVs.Speed}
	evs := [6]int{profile.EVs.HP, profile.EVs.Attack, profile.EVs.Defense, profile.EVs.SpecialAttack, profile.EVs.SpecialDefense, profile.EVs.Speed}
	return solverTemplateNative{key, ivs, evs, nature}
}

// solverNatureFacts 把现有25性格资料的升降轴转成Core五轴事实；目标等价分组/筛选/排序仍由Core执行。
func solverNatureFacts() []any {
	result := []any{}
	axes := map[string]int{"attack": 0, "defense": 1, "special_attack": 2, "special_defense": 3, "speed": 4}
	for _, nature := range configurations.Natures() {
		multipliers := []float64{1, 1, 1, 1, 1}
		if nature.IncreasedStat != nil {
			multipliers[axes[*nature.IncreasedStat]] = 1.1
			multipliers[axes[*nature.DecreasedStat]] = 0.9
		}
		result = append(result, map[string]any{"identifier": nature.Identifier, "label": nature.Label, "modifier": multipliers})
	}
	return result
}

// prepare 把input的完整知识与合法选择固定后批量用Core准备目标actual stats，最后组装正式.8目标操作。
// ctx贯穿SQL后的全部原生调用；snapshot为一次RR拥有值，不重新读取资料、不复制目标数学。
func (handler configurationSolverHandler) prepare(ctx context.Context, input solverInput, snapshot catalog.GoalSnapshot) (solverPrepared, error) {
	prepared := solverPrepared{Snapshot: snapshot, Profiles: map[string]calculatorProfile{}, Warnings: []string{}}
	subject, exists := snapshot.Pokemon[*input.Subject]
	if !exists {
		return prepared, &catalog.CalculationInputError{Message: fmt.Sprintf("unknown subject pokemon_id: %d", *input.Subject)}
	}
	ability, warning, err := solverAbility(subject, *input.Ability, "subject", "待配置 Pokémon ")
	if err != nil {
		return prepared, err
	}
	if warning != "" {
		prepared.Warnings = append(prepared.Warnings, warning)
	}
	item, err := solverItem(input.Item)
	if err != nil {
		return prepared, err
	}
	goalAbilities := make([]string, len(input.Goals))
	goalItems := make([]string, len(input.Goals))
	for index, goal := range input.Goals {
		label := "攻目标防守方"
		if *goal.Kind == "defense" {
			label = "防目标攻击方"
		}
		resolved, notice, err := solverAbility(snapshot.Pokemon[*goal.Target], *goal.Ability, "goal "+*goal.ID+" target", label)
		if err != nil {
			return prepared, err
		}
		goalAbilities[index] = resolved
		if notice != "" {
			prepared.Warnings = append(prepared.Warnings, notice)
		}
	}
	for index, goal := range input.Goals {
		goalItems[index], err = solverItem(goal.Item)
		if err != nil {
			return prepared, err
		}
	}
	operations := []any{}
	speedIndices := make([]int, len(input.Speed))
	for index, goal := range input.Speed {
		target, exists := snapshot.Pokemon[*goal.Target]
		if !exists {
			return prepared, &catalog.CalculationInputError{Message: fmt.Sprintf("unknown speed target pokemon_id: %d", *goal.Target)}
		}
		profile, err := readCalculatorProfile(*goal.Profile)
		if err != nil {
			return prepared, err
		}
		speedIndices[index] = len(operations)
		operations = append(operations, solverStatsOperation(target.Base, profile, input.Level))
	}
	// Core接收原确定性十模板和用户快照事实，按allowed_stat_presets自己去重、保序及提前停止。
	keys := []string{"max_hp_def_plus", "max_hp_spdef_plus", "max_hp_def", "max_hp_spdef", "max_hp", "max_spatk_plus", "max_atk_plus", "max_spatk_neutral", "max_atk_neutral", "no_investment"}
	keys = append(keys, input.Allowed...)
	templates := []solverTemplateNative{}
	for _, key := range keys {
		if _, exists := prepared.Profiles[key]; exists {
			continue
		}
		profile, err := readCalculatorProfile(key)
		if err != nil {
			return prepared, err
		}
		prepared.Profiles[key] = profile
		templates = append(templates, solverTemplateFact(key, profile))
	}
	goalIndices := make([]int, len(input.Goals))
	for index, goal := range input.Goals {
		target, exists := snapshot.Pokemon[*goal.Target]
		if !exists {
			return prepared, &catalog.CalculationInputError{Message: fmt.Sprintf("unknown target pokemon_id: %d", *goal.Target)}
		}
		move, exists := snapshot.Moves[*goal.Move]
		if !exists {
			return prepared, &catalog.CalculationInputError{Message: fmt.Sprintf("unknown move_id: %d", *goal.Move)}
		}
		if move.Power <= 0 {
			return prepared, &catalog.CalculationInputError{Message: "moves without fixed positive power are not supported"}
		}
		owner := *input.Subject
		message := "attack goal move is not available for subject"
		if *goal.Kind == "defense" {
			owner = *goal.Target
			message = "defense goal move is not available for target"
		}
		if !snapshot.Learnable[owner][*goal.Move] {
			return prepared, &catalog.CalculationInputError{Message: message}
		}
		profile, err := readCalculatorProfile(goal.Profile)
		if err != nil {
			return prepared, err
		}
		goalIndices[index] = len(operations)
		operations = append(operations, solverStatsOperation(target.Base, profile, input.Level))
	}
	raw, err := handler.core.batch(ctx, operations)
	if err != nil {
		return prepared, err
	}
	actual := make([]configurations.Spread, len(raw))
	for index, body := range raw {
		var result struct {
			Kind    string `json:"kind"`
			Classes []struct {
				Actual configurations.Spread `json:"actual"`
			} `json:"classes"`
		}
		if json.Unmarshal(body, &result) != nil || result.Kind != "configuration_stats" || len(result.Classes) != 1 {
			return prepared, fmt.Errorf("invalid native target stats")
		}
		actual[index] = result.Classes[0].Actual
	}
	speeds := []any{}
	for index, goal := range input.Speed {
		speeds = append(speeds, map[string]any{"goal_id": *goal.ID, "target_speed": actual[speedIndices[index]].Speed})
	}
	goals := []any{}
	for index, goal := range input.Goals {
		target, move := snapshot.Pokemon[*goal.Target], snapshot.Moves[*goal.Move]
		goals = append(goals, map[string]any{"goal_id": *goal.ID, "kind": *goal.Kind, "target": solverPokemonNative{input.Level, target.Types, actual[goalIndices[index]], goalAbilities[index], goalItems[index]}, "move": map[string]any{"type": move.Type, "category": move.Category, "power": move.Power}, "required_turns": goal.Turns, "roll_policy": goal.Roll})
	}
	kind := "configuration_templates"
	if handler.search {
		kind = "configuration_spread_search"
	}
	prepared.Operation = map[string]any{"kind": kind, "generation_id": snapshot.Rules.Generation, "subject_base": solverPokemonNative{input.Level, subject.Types, subject.Base, ability, item}, "goals": goals, "speed_goals": speeds, "max_candidates": input.Maximum, "type_chart": snapshot.Chart}
	if handler.search {
		prepared.Operation["natures"] = solverNatureFacts()
	} else {
		prepared.Operation["templates"] = templates
		prepared.Operation["allowed_stat_presets"] = input.Allowed
	}
	return prepared, nil
}
