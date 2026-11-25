package jobs

import (
	"encoding/json"
	"errors"
)

// FrozenMove 保存同一知识快照中的完整招式和初始 PP 槽；投影只能选取，不重算 PP/slot_id/effect。
// Spec/Slot 是各自拥有的原 state.v1 JSON 对象，MoveID 必须与两个对象内的 move_id 一致。
type FrozenMove struct {
	MoveID int             `json:"move_id"`
	Spec   json.RawMessage `json:"spec"`
	Slot   json.RawMessage `json:"slot"`
}

// FixedBattleTemplate 只保存一次共享完整 fixed_battle 请求与两侧合法候选池。
// Request 使用每侧至少一招的合法基础状态；worker 领取单个 case 时只替换 spec.moves/move_slots。
// 所有其他规则、当前状态、策略和属性表均原样冻结，不重查数据库，不提前展开全部 case 请求。
type FixedBattleTemplate struct {
	ContractVersion string          `json:"contract_version"`
	Request         json.RawMessage `json:"request"`
	AttackerMoves   []FrozenMove    `json:"attacker_moves"`
	DefenderMoves   []FrozenMove    `json:"defender_moves"`
}

// frozenMoveIndex 检查 pool 的协议 ID 与完整 JSON 引用，返回只读成员索引和本池实际字节数。
// pool 为一侧1..10项已由应用/Core准入的候选；此层不再次实现机制准入或战斗规则。
func frozenMoveIndex(pool []FrozenMove) (map[int]bool, int, error) {
	if len(pool) < 1 || len(pool) > 10 {
		return nil, 0, errors.New("frozen move pool must contain one to ten candidates")
	}
	index := make(map[int]bool, len(pool))
	total := 0
	for _, move := range pool {
		var spec, slot struct {
			MoveID int `json:"move_id"`
		}
		if move.MoveID <= 0 || index[move.MoveID] || json.Unmarshal(move.Spec, &spec) != nil || json.Unmarshal(move.Slot, &slot) != nil || spec.MoveID != move.MoveID || slot.MoveID != move.MoveID {
			return nil, 0, errors.New("frozen move and slot identities must be complete and unique")
		}
		index[move.MoveID] = true
		total += len(move.Spec) + len(move.Slot)
	}
	return index, total, nil
}

// templateSide 保存验证所需的只读 JSON 外壳；其他状态字段始终保留在原 Request，不复制默认值。
type templateSide struct {
	Spec struct {
		Moves []json.RawMessage `json:"moves"`
	} `json:"spec"`
	Slots []json.RawMessage `json:"move_slots"`
}

// validate 检查 side 的基础招式/槽逐项对齐且属于同一 pool；不要求 slot_id 等于位置或 move_id。
func (side templateSide) validate(pool map[int]bool) error {
	if len(side.Spec.Moves) < 1 || len(side.Spec.Moves) > 4 || len(side.Slots) != len(side.Spec.Moves) {
		return errors.New("template base state requires matching configured moves and PP slots")
	}
	seen := map[int]bool{}
	for index, spec := range side.Spec.Moves {
		var move, slot struct {
			MoveID int `json:"move_id"`
		}
		if json.Unmarshal(spec, &move) != nil || json.Unmarshal(side.Slots[index], &slot) != nil || !pool[move.MoveID] || seen[move.MoveID] || move.MoveID != slot.MoveID {
			return errors.New("template base move identities do not match the frozen pool")
		}
		seen[move.MoveID] = true
	}
	return nil
}

// Validate 检查 template 是有界 schema1/单 fixed_battle 批，且所有 cases 的两侧 ID 在对应池中。
// cases 是完整轻量配置定义；只验证协议完整性，不生成组合、规则或结果，也不更改任何输入。
func (template FixedBattleTemplate) Validate(cases []CaseDefinition) error {
	if template.ContractVersion != "fixed-battle-move-pool.v1" || len(template.Request) > 8<<20 {
		return errors.New("unsupported or oversized frozen Core template")
	}
	var batch struct {
		Version    int `json:"schema_version"`
		Operations []struct {
			Kind  string `json:"kind"`
			State struct {
				Attacker templateSide `json:"attacker"`
				Defender templateSide `json:"defender"`
			} `json:"state"`
		} `json:"operations"`
	}
	if json.Unmarshal(template.Request, &batch) != nil || batch.Version != 1 || len(batch.Operations) != 1 || batch.Operations[0].Kind != "fixed_battle" {
		return errors.New("template must contain one version 1 fixed_battle operation")
	}
	attacker, attackerBytes, err := frozenMoveIndex(template.AttackerMoves)
	if err != nil {
		return err
	}
	defender, defenderBytes, err := frozenMoveIndex(template.DefenderMoves)
	if err != nil {
		return err
	}
	// 整个共享输入受原8MiB边界限制，避免大候选池把物化后的子进程请求隐式扩展到无限大小。
	if len(template.Request)+attackerBytes+defenderBytes > 8<<20 {
		return errors.New("frozen Core template exceeds the request budget")
	}
	if err = batch.Operations[0].State.Attacker.validate(attacker); err != nil {
		return err
	}
	if err = batch.Operations[0].State.Defender.validate(defender); err != nil {
		return err
	}
	for _, item := range cases {
		for _, id := range item.AttackerMoves {
			if !attacker[id] {
				return errors.New("case attacker move is absent from the frozen pool")
			}
		}
		for _, id := range item.DefenderMoves {
			if !defender[id] {
				return errors.New("case defender move is absent from the frozen pool")
			}
		}
	}
	return nil
}
