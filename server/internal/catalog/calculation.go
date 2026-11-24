package catalog

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"pokemonbattleinference/server/internal/configurations"
)

// CalculationInputError 表示真实知识快照中不存在所选规则/宝可梦/招式；数据库异常不使用此类型。
type CalculationInputError struct{ Message string }

// Error 返回可安全公开的原业务输入错误，不包含 SQL 或连接资料。
func (err *CalculationInputError) Error() string { return err.Message }

// CalculationRules 保留原规则集上下文；Go 不根据 generation 重新推导战斗公式。
type CalculationRules struct {
	ID           string
	Name         string
	Generation   int
	VersionGroup int
}

// CalculationAbility 保存历史槽位读取结果；Implemented 是旧静态计算器合同而非完整机制承诺。
type CalculationAbility struct {
	Identifier  string `json:"identifier"`
	DisplayName string `json:"display_name"`
	Implemented bool   `json:"implemented"`
}

// CalculationPokemon 是同一只读事务中的种族值、类型与合法特性；不含派生能力值。
type CalculationPokemon struct {
	ID         int                   `json:"pokemon_id"`
	Identifier string                `json:"identifier"`
	Name       string                `json:"name"`
	Types      []int                 `json:"types"`
	Base       configurations.Spread `json:"base"`
	Abilities  []CalculationAbility  `json:"abilities"`
}

// CalculationMove 保留 version-aware 招式与原展示字段；power 的可计算性由应用校验。
type CalculationMove struct {
	ID             int
	Identifier     string
	Name           string
	Type           int
	TypeIdentifier string
	TypeName       string
	Category       string
	Power          int
}

// TypeFactor 是 Core 接受的属性表条目；percent 为数据库原 damage_factor，不在 Go 相乘。
type TypeFactor struct {
	Attacking int `json:"attacking"`
	Defending int `json:"defending"`
	Percent   int `json:"percent"`
}

// CalculationSnapshot 冻结一次请求需要的完整知识；不保存事务、连接或可变全局缓存。
type CalculationSnapshot struct {
	Rules    CalculationRules
	Attacker CalculationPokemon
	Defender CalculationPokemon
	Move     CalculationMove
	Chart    []TypeFactor
}

// Calculation 在单个 repeatable-read 事务中加载 ruleset、双方、合法招式及完整属性表。
// ctx 控制所有查询；ruleset 为原稳定标识；attacker/defender/move 为用户 ID。
// 返回自有值快照；业务缺失返回 CalculationInputError，其余错误只能映射为存储不可用。
func (store *Store) Calculation(ctx context.Context, ruleset string, attacker, defender, move int) (CalculationSnapshot, error) {
	var result CalculationSnapshot
	tx, err := store.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return result, err
	}
	defer tx.Rollback()
	err = tx.QueryRowContext(ctx, `SELECT ruleset_id,ruleset_name,generation_id,version_group_id FROM poke_champion.ruleset_context_mv WHERE ruleset_id=$1 LIMIT 1`, ruleset).Scan(&result.Rules.ID, &result.Rules.Name, &result.Rules.Generation, &result.Rules.VersionGroup)
	if errors.Is(err, sql.ErrNoRows) {
		return result, &CalculationInputError{fmt.Sprintf("unknown ruleset_id: %s", ruleset)}
	}
	if err != nil {
		return result, err
	}
	// 先读静态资料，再按相同 generation 解析历史特性；不从最新 raw 槽位直接猜合法性。
	for _, side := range []struct {
		id     int
		role   string
		target *CalculationPokemon
	}{{attacker, "attacker", &result.Attacker}, {defender, "defender", &result.Defender}} {
		var body json.RawMessage
		err = tx.QueryRowContext(ctx, `SELECT jsonb_build_object('pokemon_id',p.pokemon_id,'identifier',p.pokemon_identifier,'name',COALESCE(p.pokemon_name,p.pokemon_identifier),'types',array_remove(ARRAY[t1.id,t2.id],NULL),'base',jsonb_build_object('hp',p.hp,'attack',p.attack,'defense',p.defense,'special_attack',p.special_attack,'special_defense',p.special_defense,'speed',p.speed)) FROM poke_champion.pokemon_profile_mv p JOIN poke_raw.types t1 ON t1.identifier=p.type_1_identifier LEFT JOIN poke_raw.types t2 ON t2.identifier=p.type_2_identifier WHERE p.ruleset_id=$1 AND p.pokemon_id=$2 LIMIT 1`, ruleset, side.id).Scan(&body)
		if errors.Is(err, sql.ErrNoRows) {
			return result, &CalculationInputError{fmt.Sprintf("unknown %s pokemon_id: %d", side.role, side.id)}
		}
		if err != nil {
			return result, err
		}
		if err = json.Unmarshal(body, side.target); err != nil {
			return result, err
		}
		// 沿用旧 Abilities 端点的历史解析顺序，不用最新 generation 的槽位替代。
		if err = tx.QueryRowContext(ctx, calculationAbilitiesSQL, ruleset, side.id).Scan(&body); err != nil {
			return result, err
		}
		if err = json.Unmarshal(body, &side.target.Abilities); err != nil {
			return result, err
		}
	}
	err = tx.QueryRowContext(ctx, `SELECT move_id,move_identifier,COALESCE(move_name,move_identifier),type_id,type_identifier,COALESCE(type_name,type_identifier),damage_class_identifier,COALESCE(power,0) FROM poke_champion.move_profile_mv WHERE ruleset_id=$1 AND move_id=$2 LIMIT 1`, ruleset, move).Scan(&result.Move.ID, &result.Move.Identifier, &result.Move.Name, &result.Move.Type, &result.Move.TypeIdentifier, &result.Move.TypeName, &result.Move.Category, &result.Move.Power)
	if errors.Is(err, sql.ErrNoRows) {
		return result, &CalculationInputError{fmt.Sprintf("unknown move_id: %d", move)}
	}
	if err != nil {
		return result, err
	}
	if result.Move.Category != "physical" && result.Move.Category != "special" {
		return result, &CalculationInputError{"status moves are not supported in basic calculator"}
	}
	if result.Move.Power <= 0 {
		return result, &CalculationInputError{"moves without fixed positive power are not supported"}
	}
	var legal bool
	if err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM poke_champion.pokemon_learnset_mv WHERE ruleset_id=$1 AND pokemon_id=$2 AND move_id=$3 AND damage_class_identifier IN('physical','special') AND power>0)`, ruleset, attacker, move).Scan(&legal); err != nil {
		return result, err
	}
	if !legal {
		return result, &CalculationInputError{"move is not available for attacker in this ruleset"}
	}
	rows, err := tx.QueryContext(ctx, `SELECT damage_type_id,target_type_id,damage_factor FROM poke_champion.type_efficacy_mv WHERE ruleset_id=$1 ORDER BY damage_type_id,target_type_id`, ruleset)
	if err != nil {
		return result, err
	}
	defer rows.Close()
	result.Chart = []TypeFactor{}
	for rows.Next() {
		var factor TypeFactor
		if err = rows.Scan(&factor.Attacking, &factor.Defending, &factor.Percent); err != nil {
			return result, err
		}
		result.Chart = append(result.Chart, factor)
	}
	if err = rows.Err(); err != nil {
		return result, err
	}
	rows.Close()
	return result, tx.Commit()
}

// calculationAbilitiesSQL 只映射旧静态计算器八项 effect 标记，不在读取层复制倍率或回合规则。
const calculationAbilitiesSQL = `WITH context AS(SELECT generation_id,language_id FROM poke_champion.ruleset_context_mv WHERE ruleset_id=$1 LIMIT 1),resolved AS(SELECT pa.slot,pa.is_hidden,CASE WHEN past.ability_id IS NOT NULL THEN NULLIF(past.ability_id,0) ELSE NULLIF(pa.ability_id,0) END ability_id FROM poke_raw.pokemon_abilities pa CROSS JOIN context rc LEFT JOIN LATERAL(SELECT pap.ability_id FROM poke_raw.pokemon_abilities_past pap WHERE pap.pokemon_id=pa.pokemon_id AND pap.slot=pa.slot AND pap.is_hidden=pa.is_hidden AND pap.generation_id>=rc.generation_id ORDER BY pap.generation_id LIMIT 1) past ON true WHERE pa.pokemon_id=$2) SELECT COALESCE(jsonb_agg(jsonb_build_object('identifier',a.identifier,'display_name',COALESCE(n.name,a.identifier),'implemented',a.identifier=ANY(ARRAY['technician','adaptability','thick-fat','filter','solid-rock','sniper','multiscale','inner-focus'])) ORDER BY resolved.slot,resolved.is_hidden,a.id),'[]'::jsonb) FROM resolved CROSS JOIN context rc JOIN poke_raw.abilities a ON a.id=resolved.ability_id AND a.is_main_series IS TRUE LEFT JOIN poke_raw.ability_names n ON n.ability_id=a.id AND n.local_language_id=rc.language_id`
