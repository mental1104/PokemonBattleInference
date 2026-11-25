package nativeworker_test

import (
	"bytes"
	"context"
	"encoding/json"
	"pokemonbattleinference/server/internal/jobs"
	"testing"
)

// frozenFixtureSide 仅读取正式fixture中的完整招式/PP槽，不重建任何战斗或伤害规则。
type frozenFixtureSide struct {
	Spec struct {
		Moves []json.RawMessage `json:"moves"`
	} `json:"spec"`
	Slots []json.RawMessage `json:"move_slots"`
}

// frozenFixtureMove 为t提取side中的正式单招输入；返回拥有原始Spec/slot_id的完整冻结投影。
func frozenFixtureMove(t *testing.T, side frozenFixtureSide) jobs.FrozenMove {
	t.Helper()
	if len(side.Spec.Moves) != 1 || len(side.Slots) != 1 {
		t.Fatal("the shared battle fixture must contain one initial move per side")
	}
	var identity struct {
		ID int `json:"move_id"`
	}
	if err := json.Unmarshal(side.Spec.Moves[0], &identity); err != nil {
		t.Fatal(err)
	}
	return jobs.FrozenMove{MoveID: identity.ID, Spec: side.Spec.Moves[0], Slot: side.Slots[0]}
}

// alternateFrozenMove 为t给move增加显式身份，完整复用相同规则字段，供验证真正按case选择而非总用代表招式。
func alternateFrozenMove(t *testing.T, move jobs.FrozenMove) jobs.FrozenMove {
	t.Helper()
	var spec, slot map[string]json.RawMessage
	if err := json.Unmarshal(move.Spec, &spec); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(move.Slot, &slot); err != nil {
		t.Fatal(err)
	}
	spec["move_id"], spec["name"] = json.RawMessage("700001"), json.RawMessage(`"alternate-punch"`)
	slot["move_id"], slot["slot_id"] = json.RawMessage("700001"), json.RawMessage("900003")
	encodedSpec, err := json.Marshal(spec)
	if err != nil {
		t.Fatal(err)
	}
	encodedSlot, err := json.Marshal(slot)
	if err != nil {
		t.Fatal(err)
	}
	return jobs.FrozenMove{MoveID: 700001, Spec: encodedSpec, Slot: encodedSlot}
}

// TestSharedTemplateProjectsRealBattlesAfterPostgresReload 以两个不同技能组验证共享定义经PG重载后真实构图和精确结果。
func TestSharedTemplateProjectsRealBattlesAfterPostgresReload(t *testing.T) {
	store, _, options := database(t)
	request := fixedRequest(t, "attacker", 100)
	var batch struct {
		Operations []struct {
			State struct {
				Attacker frozenFixtureSide `json:"attacker"`
				Defender frozenFixtureSide `json:"defender"`
			} `json:"state"`
		} `json:"operations"`
	}
	if err := json.Unmarshal(request, &batch); err != nil {
		t.Fatal(err)
	}
	if len(batch.Operations) != 1 {
		t.Fatal("one fixed battle operation is required")
	}
	attacker := frozenFixtureMove(t, batch.Operations[0].State.Attacker)
	defender := frozenFixtureMove(t, batch.Operations[0].State.Defender)
	alternate := alternateFrozenMove(t, attacker)
	value := definition("fixed-one-on-one-job-shared-template", options.Revision, 2)
	value.Spec.ProcessCount = 2
	value.CoreTemplate = &jobs.FixedBattleTemplate{ContractVersion: "fixed-battle-move-pool.v1", Request: request,
		AttackerMoves: []jobs.FrozenMove{attacker, alternate}, DefenderMoves: []jobs.FrozenMove{defender}}
	for index := range value.Cases {
		value.Cases[index].CoreRequest = nil
		value.Cases[index].AttackerMoves = []int{attacker.MoveID}
		value.Cases[index].DefenderMoves = []int{defender.MoveID}
	}
	value.Cases[1].AttackerMoves = []int{alternate.MoveID}
	// Store.Create和幂等重试都只保存一个完整模板；RunOnce必须自行从PG读取，不能使用本地value继续计算。
	create(t, store, value)
	worked, err := workerFor(t, store, options).RunOnce(context.Background())
	if err != nil || !worked {
		t.Fatalf("worked=%v err=%v", worked, err)
	}
	for _, item := range value.Cases {
		result, err := store.Result(context.Background(), value.ID, item.PairID)
		if err != nil || result == nil || result.Status != jobs.Succeeded || result.AttackerWin == nil ||
			*result.AttackerWin != (jobs.Fraction{Numerator: "1", Denominator: "1"}) || result.Nodes != 2 || result.Edges != 1 {
			t.Fatalf("actual shared-template battle failed: %+v err=%v", result, err)
		}
	}
	saved, err := store.Definition(context.Background(), value.ID)
	if err != nil || saved.CoreTemplate == nil || !bytes.Equal(saved.CoreTemplate.Request, request) {
		t.Fatalf("shared input was mutated: err=%v", err)
	}
	for _, item := range saved.Cases {
		if len(item.CoreRequest) != 0 {
			t.Fatal("completed cases must not acquire duplicate materialized Core requests")
		}
	}
}
