package nativeworker

import (
	"encoding/json"
	"errors"
	"pokemonbattleinference/server/internal/jobs"
)

// requestProjector 只保存一份不可变传输骨架和两侧原招式池，不缓存各case展开后的完整请求。
// 所有map在构造后只读，单case投影创建自己的小map，允许并行child安全读取同一模板。
type requestProjector struct {
	batch     map[string]json.RawMessage
	operation map[string]json.RawMessage
	state     map[string]json.RawMessage
	attacker  battlerProjection
	defender  battlerProjection
}

// battlerProjection 保存一侧原始字段/Spec和完整冻结Spec/PP槽；不计算能力、状态或招式效果。
type battlerProjection struct {
	value map[string]json.RawMessage
	spec  map[string]json.RawMessage
	moves map[int]jobs.FrozenMove
}

// projectionObject 在JSON传输边界读取data为对象；拒绝null/缺失，返回保留每个原始值的字段表。
func projectionObject(data json.RawMessage) (map[string]json.RawMessage, error) {
	var value map[string]json.RawMessage
	if err := json.Unmarshal(data, &value); err != nil {
		return nil, err
	}
	if value == nil {
		return nil, errors.New("frozen projection object is required")
	}
	return value, nil
}

// projectionCopy 为value复制字段索引；RawMessage字节始终只读，避免复制共享属性矩阵等大字段。
func projectionCopy(value map[string]json.RawMessage) map[string]json.RawMessage {
	result := make(map[string]json.RawMessage, len(value))
	for name, encoded := range value {
		result[name] = encoded
	}
	return result
}

// newBattlerProjection 为data中的一侧建立pool索引；完整机制准入由冻结Definition的Core结果负责。
func newBattlerProjection(data json.RawMessage, pool []jobs.FrozenMove) (battlerProjection, error) {
	value, err := projectionObject(data)
	if err != nil {
		return battlerProjection{}, err
	}
	spec, err := projectionObject(value["spec"])
	if err != nil {
		return battlerProjection{}, err
	}
	moves := make(map[int]jobs.FrozenMove, len(pool))
	for _, move := range pool {
		if move.MoveID <= 0 || !json.Valid(move.Spec) || !json.Valid(move.Slot) {
			return battlerProjection{}, errors.New("invalid frozen move projection")
		}
		if _, exists := moves[move.MoveID]; exists {
			return battlerProjection{}, errors.New("duplicate frozen move projection")
		}
		moves[move.MoveID] = move
	}
	return battlerProjection{value: value, spec: spec, moves: moves}, nil
}

// newRequestProjector 接收已验证的可选template；nil保持旧完整CoreRequest模式，不增加默认规则。
func newRequestProjector(template *jobs.FixedBattleTemplate) (*requestProjector, error) {
	projector := &requestProjector{}
	if template == nil {
		return projector, nil
	}
	batch, err := projectionObject(template.Request)
	if err != nil {
		return nil, err
	}
	var schema int
	var operations []json.RawMessage
	if json.Unmarshal(batch["schema_version"], &schema) != nil || schema != 1 ||
		json.Unmarshal(batch["operations"], &operations) != nil || len(operations) != 1 {
		return nil, errors.New("shared template requires one version 1 operation")
	}
	operation, err := projectionObject(operations[0])
	if err != nil {
		return nil, err
	}
	var kind string
	if json.Unmarshal(operation["kind"], &kind) != nil || kind != "fixed_battle" {
		return nil, errors.New("shared template requires fixed_battle")
	}
	state, err := projectionObject(operation["state"])
	if err != nil {
		return nil, err
	}
	attacker, err := newBattlerProjection(state["attacker"], template.AttackerMoves)
	if err != nil {
		return nil, err
	}
	defender, err := newBattlerProjection(state["defender"], template.DefenderMoves)
	if err != nil {
		return nil, err
	}
	projector.batch, projector.operation, projector.state = batch, operation, state
	projector.attacker, projector.defender = attacker, defender
	return projector, nil
}

// project 按已冻结的ids选择完整Spec和PP槽；顺序、slot_id及所有其他原始状态保持原值。
func (side battlerProjection) project(ids []int) (json.RawMessage, error) {
	moves := make([]json.RawMessage, len(ids))
	slots := make([]json.RawMessage, len(ids))
	for index, id := range ids {
		move, exists := side.moves[id]
		if !exists {
			return nil, errors.New("case refers to a move outside its frozen pool")
		}
		moves[index], slots[index] = move.Spec, move.Slot
	}
	encodedMoves, err := json.Marshal(moves)
	if err != nil {
		return nil, err
	}
	encodedSlots, err := json.Marshal(slots)
	if err != nil {
		return nil, err
	}
	spec := projectionCopy(side.spec)
	spec["moves"] = encodedMoves
	encodedSpec, err := json.Marshal(spec)
	if err != nil {
		return nil, err
	}
	value := projectionCopy(side.value)
	value["spec"], value["move_slots"] = encodedSpec, encodedSlots
	return json.Marshal(value)
}

// request 为单个已领取item组装请求；只在此时分配完整字节，旧模式直接借用只读CoreRequest。
func (projector *requestProjector) request(item jobs.CaseDefinition) ([]byte, error) {
	if projector.batch == nil {
		if len(item.CoreRequest) == 0 {
			return nil, errors.New("case has no frozen Core request")
		}
		return item.CoreRequest, nil
	}
	attacker, err := projector.attacker.project(item.AttackerMoves)
	if err != nil {
		return nil, err
	}
	defender, err := projector.defender.project(item.DefenderMoves)
	if err != nil {
		return nil, err
	}
	state := projectionCopy(projector.state)
	state["attacker"], state["defender"] = attacker, defender
	encodedState, err := json.Marshal(state)
	if err != nil {
		return nil, err
	}
	operation := projectionCopy(projector.operation)
	operation["state"] = encodedState
	encodedOperations, err := json.Marshal([]map[string]json.RawMessage{operation})
	if err != nil {
		return nil, err
	}
	batch := projectionCopy(projector.batch)
	batch["operations"] = encodedOperations
	result, err := json.Marshal(batch)
	if err == nil && len(result) > 8<<20 {
		return nil, errors.New("projected Core request exceeds the request budget")
	}
	return result, err
}
