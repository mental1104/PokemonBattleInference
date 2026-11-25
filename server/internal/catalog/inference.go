package catalog

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"pokemonbattleinference/server/internal/configurations"
)

// MechanismCapability 保存原 repository 的保守资料分类，不代表 Core factory 的最终准入。
// status/reason 必须独立传给 Core；Go 不根据它过滤合法候选或提升 effect 支持。
type MechanismCapability struct {
	Source     string `json:"source_kind"`
	Identifier string `json:"identifier"`
	Status     string `json:"status"`
	Reason     string `json:"reason"`
}

// InferenceRules 是同时匹配 ruleset 与精确 version group 的原规则轴。
type InferenceRules struct {
	ID                string `json:"ruleset_id"`
	Name              string `json:"ruleset_name"`
	Generation        int    `json:"generation_id"`
	VersionGroup      int    `json:"version_group_id"`
	VersionIdentifier string `json:"version_group_identifier"`
}

// InferenceType 保存原数据库整数 ID、本地化名称和稳定 identifier，不在 Go 内置第二张属性表。
type InferenceType struct {
	ID         int    `json:"type_id"`
	Identifier string `json:"identifier"`
	Name       string `json:"display_name"`
}

// InferenceAbility 是历史槽位解析、按 ability_id 去重后的全部合法特性，包括未实现候选。
type InferenceAbility struct {
	ID         int                 `json:"ability_id"`
	Identifier string              `json:"identifier"`
	Name       string              `json:"display_name"`
	Slot       int                 `json:"slot"`
	Hidden     bool                `json:"is_hidden"`
	Effect     string              `json:"effect_identifier"`
	Capability MechanismCapability `json:"capability"`
}

// InferenceMove 完整冻结历史招式输入；nil power/accuracy/effect 保留旧零哨兵映射。
type InferenceMove struct {
	ID               int                 `json:"move_id"`
	Identifier       string              `json:"identifier"`
	Name             string              `json:"display_name"`
	Type             InferenceType       `json:"type"`
	Category         string              `json:"category"`
	Power            *int                `json:"power"`
	PP               int                 `json:"pp"`
	Accuracy         *int                `json:"accuracy"`
	Priority         int                 `json:"priority"`
	TargetID         int                 `json:"target_id"`
	TargetIdentifier string              `json:"target_identifier"`
	EffectID         *int                `json:"effect_id"`
	EffectChance     *int                `json:"effect_chance"`
	Effect           *string             `json:"effect_identifier"`
	Capability       MechanismCapability `json:"capability"`
}

// InferenceItem 是受控且在该 generation 存在的持有道具；无道具使用 nil ID/effect。
type InferenceItem struct {
	ID         *int                `json:"item_id"`
	Identifier string              `json:"identifier"`
	Name       string              `json:"display_name"`
	Effect     *string             `json:"effect_identifier"`
	Capability MechanismCapability `json:"capability"`
}

// InferencePokemon 保留原完整 profile 的形态、进化、类型、种族值与全部合法候选。
// 它没有派生 stats、动作组合或当前 HP；这些输入由 Core/业务选择合同解释。
type InferencePokemon struct {
	ID                int                   `json:"pokemon_id"`
	Identifier        string                `json:"identifier"`
	Name              string                `json:"display_name"`
	SpeciesID         int                   `json:"species_id"`
	SpeciesIdentifier string                `json:"species_identifier"`
	Form              *string               `json:"form_identifier"`
	DefaultForm       bool                  `json:"is_default_form"`
	BattleOnly        bool                  `json:"is_battle_only_form"`
	Mega              bool                  `json:"is_mega_form"`
	Types             []InferenceType       `json:"types"`
	Base              configurations.Spread `json:"base_stats"`
	CanEvolve         bool                  `json:"can_evolve"`
	Abilities         []InferenceAbility    `json:"abilities"`
	Moves             []InferenceMove       `json:"moves"`
}

// InferenceSnapshot 是一次业务提交的独立知识快照，不借用连接/事务或共享可变缓存。
type InferenceSnapshot struct {
	Rules   InferenceRules     `json:"ruleset"`
	Pokemon []InferencePokemon `json:"pokemon"`
	Items   []InferenceItem    `json:"items"`
	Chart   []TypeFactor       `json:"type_chart"`
}

// Inference 在同一 repeatable-read 快照读取精确规则轴、pokemonIDs 顺序的完整 profiles 和受控道具。
// ctx 取消全部 SQL；ruleset/versionGroup 必须共同存在；pokemonIDs 为空或对象不存在为输入错误。
// 返回值保留全部合法候选，绝不按 repository 支持状态预先删掉分母；失败整体不返回可用半快照。
func (store *Store) Inference(ctx context.Context, ruleset string, versionGroup int, pokemonIDs []int) (InferenceSnapshot, error) {
	var result InferenceSnapshot
	if len(pokemonIDs) == 0 {
		return result, &CalculationInputError{Message: "at least one pokemon_id is required"}
	}
	tx, err := store.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return result, err
	}
	defer tx.Rollback()
	err = tx.QueryRowContext(ctx, `SELECT ruleset_id,ruleset_name,generation_id,version_group_id,version_group_identifier FROM poke_champion.ruleset_context_mv WHERE ruleset_id=$1 AND version_group_id=$2 LIMIT 1`, ruleset, versionGroup).Scan(&result.Rules.ID, &result.Rules.Name, &result.Rules.Generation, &result.Rules.VersionGroup, &result.Rules.VersionIdentifier)
	if errors.Is(err, sql.ErrNoRows) {
		return result, &CalculationInputError{Message: "ruleset and version group are not available"}
	}
	if err != nil {
		return result, err
	}
	result.Pokemon = make([]InferencePokemon, 0, len(pokemonIDs))
	for _, id := range pokemonIDs {
		pokemon, readErr := readInferencePokemon(ctx, tx, ruleset, versionGroup, id)
		if readErr != nil {
			return InferenceSnapshot{}, readErr
		}
		result.Pokemon = append(result.Pokemon, pokemon)
	}
	var data json.RawMessage
	if err = tx.QueryRowContext(ctx, inferenceItemsSQL, ruleset, versionGroup).Scan(&data); err != nil {
		return InferenceSnapshot{}, err
	}
	if err = json.Unmarshal(data, &result.Items); err != nil {
		return InferenceSnapshot{}, err
	}
	for index := range result.Items {
		item := &result.Items[index]
		item.Capability = MechanismCapability{"item", item.Identifier, "supported", "当前 domain 已注册该道具的战斗 effect。"}
		if item.ID == nil {
			item.Capability = MechanismCapability{"item", "none", "no_effect", "该配置明确表示不携带道具。"}
		}
	}
	if err = tx.QueryRowContext(ctx, `SELECT COALESCE(jsonb_agg(jsonb_build_object('attacking',damage_type_id,'defending',target_type_id,'percent',damage_factor) ORDER BY damage_type_id,target_type_id),'[]'::jsonb) FROM poke_champion.type_efficacy_mv WHERE ruleset_id=$1 AND generation_id=$2`, ruleset, result.Rules.Generation).Scan(&data); err != nil {
		return InferenceSnapshot{}, err
	}
	if err = json.Unmarshal(data, &result.Chart); err != nil {
		return InferenceSnapshot{}, err
	}
	return result, tx.Commit()
}

// readInferencePokemon 用 tx 的已冻结知识事务读取 id 的全部原投影；ctx 控制取消。
// ruleset/versionGroup 是共同主轴，未找到返回业务缺失，不做跨版本 fallback。
func readInferencePokemon(ctx context.Context, tx *sql.Tx, ruleset string, versionGroup, id int) (InferencePokemon, error) {
	var result InferencePokemon
	var data json.RawMessage
	err := tx.QueryRowContext(ctx, inferencePokemonSQL, ruleset, versionGroup, id).Scan(&data)
	if errors.Is(err, sql.ErrNoRows) {
		return result, &CalculationInputError{Message: fmt.Sprintf("pokemon %d is not available in the requested version group", id)}
	}
	if err != nil {
		return result, err
	}
	if err = json.Unmarshal(data, &result); err != nil {
		return result, err
	}
	if err = tx.QueryRowContext(ctx, inferenceAbilitiesSQL, ruleset, versionGroup, id).Scan(&data); err != nil {
		return result, err
	}
	if err = json.Unmarshal(data, &result.Abilities); err != nil {
		return result, err
	}
	for index := range result.Abilities {
		ability := &result.Abilities[index]
		ability.Effect = ability.Identifier
		ability.Capability = MechanismCapability{"ability", ability.Identifier, "unsupported", "该特性在当前 version group 合法，但 domain 尚未实现对应 effect。"}
		switch ability.Identifier {
		case "technician", "adaptability", "thick-fat", "filter", "solid-rock", "sniper", "multiscale", "inner-focus":
			ability.Capability.Status = "supported"
			ability.Capability.Reason = "当前 domain 已注册该特性的战斗 effect。"
		}
	}
	if err = tx.QueryRowContext(ctx, inferenceMovesSQL, ruleset, versionGroup, id).Scan(&data); err != nil {
		return result, err
	}
	if err = json.Unmarshal(data, &result.Moves); err != nil {
		return result, err
	}
	for index := range result.Moves {
		classifyInferenceMove(&result.Moves[index])
	}
	return result, nil
}

// classifyInferenceMove 逐字保留 owning repository._move_capability 的数据完整性分类。
// move 是本次独占投影；这里只填 effect 选择和原保守 reason，不执行 factory 或最终准入。
func classifyInferenceMove(move *InferenceMove) {
	identifier := move.Identifier
	move.Effect = &identifier
	move.Capability = MechanismCapability{Source: "move", Identifier: identifier}
	switch {
	case move.Category == "status":
		move.Capability.Status = "unsupported"
		move.Capability.Reason = "变化招式合法但当前通用回合执行器尚未实现其具体 effect。"
	case move.Power == nil:
		move.Capability.Status = "unsupported"
		move.Capability.Reason = "该攻击招式使用变化威力，当前 domain 尚无对应威力解析器。"
	case move.EffectID == nil || *move.EffectID == 1:
		move.Effect = nil
		move.Capability.Identifier = "base-damage"
		move.Capability.Status = "supported"
		move.Capability.Reason = "该招式只需要当前已支持的基础命中、PP 与伤害语义。"
	default:
		move.Capability.Status = "partial"
		move.Capability.Reason = "基础命中、PP 与伤害可执行，但 PokeAPI 附加 effect 尚未完整实现。"
	}
}

// inferencePokemonSQL 沿原 profile 读取进化与形态，保留第二属性为空；不硬编码特定宝可梦。
const inferencePokemonSQL = `SELECT jsonb_build_object('pokemon_id',p.pokemon_id,'identifier',p.pokemon_identifier,'display_name',COALESCE(p.pokemon_name,p.pokemon_identifier),'species_id',p.species_id,'species_identifier',p.species_identifier,'form_identifier',p.form_identifier,'is_default_form',p.is_default_form,'is_battle_only_form',p.is_battle_only_form,'is_mega_form',p.is_mega_form,'types',jsonb_build_array(jsonb_build_object('type_id',p.type_1_id,'identifier',p.type_1_identifier,'display_name',COALESCE(p.type_1_name,p.type_1_identifier)))||CASE WHEN p.type_2_id IS NULL OR p.type_2_identifier IS NULL THEN '[]'::jsonb ELSE jsonb_build_array(jsonb_build_object('type_id',p.type_2_id,'identifier',p.type_2_identifier,'display_name',COALESCE(p.type_2_name,p.type_2_identifier))) END,'base_stats',jsonb_build_object('hp',p.hp,'attack',p.attack,'defense',p.defense,'special_attack',p.special_attack,'special_defense',p.special_defense,'speed',p.speed),'can_evolve',EXISTS(SELECT 1 FROM poke_raw.pokemon_species child WHERE child.evolves_from_species_id=p.species_id AND child.generation_id<=p.generation_id)) FROM poke_champion.pokemon_profile_mv p WHERE p.ruleset_id=$1 AND p.version_group_id=$2 AND p.pokemon_id=$3 LIMIT 1`

// inferenceAbilitiesSQL 用原 generation>=历史边界恢复槽位，按 ability_id 去重而非按当前 slot 猜测。
const inferenceAbilitiesSQL = `WITH context AS(SELECT generation_id,language_id FROM poke_champion.ruleset_context_mv WHERE ruleset_id=$1 AND version_group_id=$2),resolved AS(SELECT pa.slot,pa.is_hidden,CASE WHEN past.ability_id IS NOT NULL THEN NULLIF(past.ability_id,0) ELSE NULLIF(pa.ability_id,0) END ability_id FROM poke_raw.pokemon_abilities pa CROSS JOIN context rc LEFT JOIN LATERAL(SELECT pap.ability_id FROM poke_raw.pokemon_abilities_past pap WHERE pap.pokemon_id=pa.pokemon_id AND pap.slot=pa.slot AND pap.is_hidden=pa.is_hidden AND pap.generation_id>=rc.generation_id ORDER BY pap.generation_id LIMIT 1) past ON true WHERE pa.pokemon_id=$3) SELECT COALESCE(jsonb_agg(payload ORDER BY ability_id),'[]'::jsonb) FROM(SELECT DISTINCT ON(a.id) a.id ability_id,jsonb_build_object('ability_id',a.id,'identifier',a.identifier,'display_name',COALESCE(n.name,a.identifier),'slot',r.slot,'is_hidden',r.is_hidden) payload FROM resolved r CROSS JOIN context rc JOIN poke_raw.abilities a ON a.id=r.ability_id AND a.is_main_series IS TRUE LEFT JOIN poke_raw.ability_names n ON n.ability_id=a.id AND n.local_language_id=rc.language_id ORDER BY a.id,r.slot,r.is_hidden) selected`

// inferenceMovesSQL 保留所有合法物理/特殊/变化招式，联合精确 version group，不删除机制未实现记录。
const inferenceMovesSQL = `SELECT COALESCE(jsonb_agg(payload ORDER BY move_id),'[]'::jsonb) FROM(SELECT DISTINCT m.move_id,jsonb_build_object('move_id',m.move_id,'identifier',m.move_identifier,'display_name',COALESCE(m.move_name,m.move_identifier),'type',jsonb_build_object('type_id',m.type_id,'identifier',m.type_identifier,'display_name',COALESCE(m.type_name,m.type_identifier)),'category',m.damage_class_identifier,'power',CASE WHEN m.power>0 THEN m.power ELSE NULL END,'pp',m.pp,'accuracy',CASE WHEN m.accuracy>0 THEN m.accuracy ELSE NULL END,'priority',m.priority,'target_id',m.target_id,'target_identifier',m.target_identifier,'effect_id',CASE WHEN m.effect_id>0 THEN m.effect_id ELSE NULL END,'effect_chance',CASE WHEN m.effect_chance>0 THEN m.effect_chance ELSE NULL END) payload FROM poke_champion.pokemon_learnset_mv l JOIN poke_champion.move_profile_mv m ON m.ruleset_id=l.ruleset_id AND m.version_group_id=l.version_group_id AND m.move_id=l.move_id WHERE l.ruleset_id=$1 AND l.version_group_id=$2 AND l.pokemon_id=$3) selected`

// inferenceItemsSQL 复用原五项受控道具的 generation 存在边界；不套用静态 calculator 的额外分类过滤。
const inferenceItemsSQL = `WITH context AS(SELECT generation_id,language_id FROM poke_champion.ruleset_context_mv WHERE ruleset_id=$1 AND version_group_id=$2) SELECT jsonb_build_array(jsonb_build_object('item_id',NULL,'identifier','none','display_name','不携带道具','effect_identifier',NULL))||COALESCE(jsonb_agg(jsonb_build_object('item_id',i.id,'identifier',i.identifier,'display_name',COALESCE(n.name,i.identifier),'effect_identifier',i.identifier) ORDER BY i.id),'[]'::jsonb) FROM poke_raw.items i CROSS JOIN context rc LEFT JOIN poke_raw.item_names n ON n.item_id=i.id AND n.local_language_id=rc.language_id WHERE i.identifier=ANY(ARRAY['life-orb','choice-band','choice-specs','expert-belt','eviolite']) AND EXISTS(SELECT 1 FROM poke_raw.item_game_indices g WHERE g.item_id=i.id AND g.generation_id<=rc.generation_id)`
