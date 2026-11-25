package catalog

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
)

// GoalPokemon 补齐原目标求解展示所需的形态/属性名称；基础能力和历史合法特性仍来自原MV。
type GoalPokemon struct {
	CalculationPokemon
	Form            *string  `json:"form_identifier"`
	TypeIdentifiers []string `json:"type_identifiers"`
	TypeNames       []string `json:"type_names"`
}

// GoalSnapshot 冻结一次模板/EV请求的全部规则、主体/目标、招式合法性及属性表，不含任何计算结果。
type GoalSnapshot struct {
	Rules     CalculationRules
	Pokemon   map[int]GoalPokemon
	Moves     map[int]CalculationMove
	Learnable map[int]map[int]bool
	Chart     []TypeFactor
}

// Goals 在同一只读RR事务加载所有ID；缺失Pokemon/move保留为空映射，交原应用顺序输出角色明确的错误。
// ctx控制全部查询；pokemonIDs/moveIDs只作为SQL参数，空move列表允许纯速度目标；不计算模板、伤害或速度。
func (store *Store) Goals(ctx context.Context, ruleset string, pokemonIDs, moveIDs []int) (GoalSnapshot, error) {
	result := GoalSnapshot{Pokemon: map[int]GoalPokemon{}, Moves: map[int]CalculationMove{}, Learnable: map[int]map[int]bool{}, Chart: []TypeFactor{}}
	tx, err := store.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return result, err
	}
	defer tx.Rollback()
	err = tx.QueryRowContext(ctx, `SELECT ruleset_id,ruleset_name,generation_id,version_group_id FROM poke_champion.ruleset_context_mv WHERE ruleset_id=$1 LIMIT 1`, ruleset).Scan(&result.Rules.ID, &result.Rules.Name, &result.Rules.Generation, &result.Rules.VersionGroup)
	if errors.Is(err, sql.ErrNoRows) {
		return result, &CalculationInputError{Message: fmt.Sprintf("unknown ruleset_id: %s", ruleset)}
	}
	if err != nil {
		return result, err
	}
	for _, id := range pokemonIDs {
		if _, exists := result.Pokemon[id]; exists {
			continue
		}
		var body json.RawMessage
		err = tx.QueryRowContext(ctx, `SELECT jsonb_build_object('pokemon_id',p.pokemon_id,'identifier',p.pokemon_identifier,'name',COALESCE(p.pokemon_name,p.pokemon_identifier),'form_identifier',p.form_identifier,'types',array_remove(ARRAY[t1.id,t2.id],NULL),'type_identifiers',array_remove(ARRAY[p.type_1_identifier,p.type_2_identifier],NULL),'type_names',array_remove(ARRAY[p.type_1_name,p.type_2_name],NULL),'base',jsonb_build_object('hp',p.hp,'attack',p.attack,'defense',p.defense,'special_attack',p.special_attack,'special_defense',p.special_defense,'speed',p.speed)) FROM poke_champion.pokemon_profile_mv p JOIN poke_raw.types t1 ON t1.identifier=p.type_1_identifier LEFT JOIN poke_raw.types t2 ON t2.identifier=p.type_2_identifier WHERE p.ruleset_id=$1 AND p.pokemon_id=$2 LIMIT 1`, ruleset, id).Scan(&body)
		if errors.Is(err, sql.ErrNoRows) {
			continue
		}
		if err != nil {
			return result, err
		}
		var pokemon GoalPokemon
		if err = json.Unmarshal(body, &pokemon); err != nil {
			return result, err
		}
		if err = tx.QueryRowContext(ctx, calculationAbilitiesSQL, ruleset, id).Scan(&body); err != nil {
			return result, err
		}
		if err = json.Unmarshal(body, &pokemon.Abilities); err != nil {
			return result, err
		}
		result.Pokemon[id] = pokemon
	}
	for _, id := range moveIDs {
		if _, exists := result.Moves[id]; exists {
			continue
		}
		var move CalculationMove
		err = tx.QueryRowContext(ctx, `SELECT move_id,move_identifier,COALESCE(move_name,move_identifier),type_id,type_identifier,COALESCE(type_name,type_identifier),damage_class_identifier,COALESCE(power,0) FROM poke_champion.move_profile_mv WHERE ruleset_id=$1 AND move_id=$2 LIMIT 1`, ruleset, id).Scan(&move.ID, &move.Identifier, &move.Name, &move.Type, &move.TypeIdentifier, &move.TypeName, &move.Category, &move.Power)
		if errors.Is(err, sql.ErrNoRows) {
			continue
		}
		if err != nil {
			return result, err
		}
		result.Moves[id] = move
	}
	if len(moveIDs) > 0 {
		rows, queryErr := tx.QueryContext(ctx, `SELECT DISTINCT pokemon_id,move_id FROM poke_champion.pokemon_learnset_mv WHERE ruleset_id=$1 AND pokemon_id=ANY($2::integer[]) AND move_id=ANY($3::integer[])`, ruleset, pokemonIDs, moveIDs)
		if queryErr != nil {
			return result, queryErr
		}
		for rows.Next() {
			var pokemon, move int
			if err = rows.Scan(&pokemon, &move); err != nil {
				rows.Close()
				return result, err
			}
			if result.Learnable[pokemon] == nil {
				result.Learnable[pokemon] = map[int]bool{}
			}
			result.Learnable[pokemon][move] = true
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return result, err
		}
	}
	rows, err := tx.QueryContext(ctx, `SELECT damage_type_id,target_type_id,damage_factor FROM poke_champion.type_efficacy_mv WHERE ruleset_id=$1 ORDER BY damage_type_id,target_type_id`, ruleset)
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
