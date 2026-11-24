package catalog

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

// LegacyPokemon 是旧director所需全Pokedex原始事实，不受Champion白名单或招式学习池限制。
type LegacyPokemon struct {
	ID    int      `json:"id"`
	Base  [6]int64 `json:"base"`
	Types []int    `json:"types"`
}

// LegacySnapshot 冻结旧API的双方基础/属性和当前固定raw属性表；不含任何能力/伤害派生值。
type LegacySnapshot struct {
	Attacker  LegacyPokemon
	Defender  LegacyPokemon
	TypeNames map[string]int
	Chart     []TypeFactor
}

// LegacyDamage 在同一只读RR事务读取全raw Pokemon；ctx取消中断查询，不回退最新MV或内置中性属性。
// attacker/defender沿旧id输入，缺失返回原历史director文案；原TypeHelper表的兼容性由完整知识差分验证。
func (store *Store) LegacyDamage(ctx context.Context, attacker, defender int) (LegacySnapshot, error) {
	result := LegacySnapshot{TypeNames: map[string]int{}, Chart: []TypeFactor{}}
	tx, err := store.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return result, err
	}
	defer tx.Rollback()
	for _, side := range []struct {
		id     int
		target *LegacyPokemon
	}{{attacker, &result.Attacker}, {defender, &result.Defender}} {
		var data json.RawMessage
		err = tx.QueryRowContext(ctx, `SELECT jsonb_build_object('id',p.id,'base',(SELECT jsonb_agg(s.base_stat ORDER BY s.stat_id) FROM poke_raw.pokemon_stats s WHERE s.pokemon_id=p.id AND s.stat_id BETWEEN 1 AND 6),'types',(SELECT jsonb_agg(t.type_id ORDER BY t.slot) FROM poke_raw.pokemon_types t WHERE t.pokemon_id=p.id),'slots',(SELECT jsonb_agg(t.slot ORDER BY t.slot) FROM poke_raw.pokemon_types t WHERE t.pokemon_id=p.id)) FROM poke_raw.pokemon p WHERE p.id=$1`, side.id).Scan(&data)
		if errors.Is(err, sql.ErrNoRows) {
			return result, &CalculationInputError{Message: fmt.Sprintf("Pokemon with id %d not found.", side.id)}
		}
		if err != nil {
			return result, err
		}
		var raw struct {
			ID    int     `json:"id"`
			Base  []int64 `json:"base"`
			Types []int   `json:"types"`
			Slots []int   `json:"slots"`
		}
		if err = json.Unmarshal(data, &raw); err != nil {
			return result, err
		}
		if len(raw.Base) != 6 || len(raw.Types) < 1 || len(raw.Types) > 2 || len(raw.Slots) != len(raw.Types) || raw.Slots[0] != 1 || len(raw.Slots) == 2 && raw.Slots[1] != 2 {
			return result, fmt.Errorf("incomplete raw legacy Pokemon knowledge")
		}
		// 不把缺失主属性的第二槽压成第一槽，也不把新/未知类型改成normal或直接删除；原始ID交Core明确拒绝。
		side.target.ID, side.target.Types = raw.ID, raw.Types
		copy(side.target.Base[:], raw.Base)
	}
	rows, err := tx.QueryContext(ctx, `SELECT id,identifier FROM poke_raw.types WHERE id BETWEEN 1 AND 18 ORDER BY id`)
	if err != nil {
		return result, err
	}
	for rows.Next() {
		var id int
		var name string
		if err = rows.Scan(&id, &name); err != nil {
			rows.Close()
			return result, err
		}
		result.TypeNames[strings.ToUpper(name)] = id
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return result, err
	}
	rows, err = tx.QueryContext(ctx, `SELECT damage_type_id,target_type_id,damage_factor FROM poke_raw.type_efficacy WHERE damage_type_id BETWEEN 1 AND 18 AND target_type_id BETWEEN 1 AND 18 ORDER BY damage_type_id,target_type_id`)
	if err != nil {
		return result, err
	}
	defer rows.Close()
	for rows.Next() {
		var factor TypeFactor
		if err = rows.Scan(&factor.Attacking, &factor.Defending, &factor.Percent); err != nil {
			return result, err
		}
		result.Chart = append(result.Chart, factor)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return result, err
	}
	return result, tx.Commit()
}
