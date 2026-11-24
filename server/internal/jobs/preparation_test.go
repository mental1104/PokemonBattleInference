package jobs_test

import (
	"context"
	"errors"
	"pokemonbattleinference/server/internal/jobs"
	"reflect"
	"testing"
	"time"
)

// TestFrozenPreparationFailurePostgres 验证真实 PG 往返/幂等和三种输入模式互斥，不能把准备失败伪装成战斗请求。
func TestFrozenPreparationFailurePostgres(t *testing.T) {
	store, _ := database(t)
	ctx := context.Background()
	input := definition("frozen-preparation-failure", 2)
	input.PreparationFailure = &jobs.PreparationFailure{Code: "invalid_configuration", Diagnostic: "ConfigurationSpaceError: unknown stat profile preset: unknown-profile"}
	for index := range input.Cases {
		input.Cases[index].CoreRequest = nil
	}
	now := time.Now().UTC()
	if created, err := store.Create(ctx, input, now); err != nil || !created {
		t.Fatalf("create preparation failure: created=%v err=%v", created, err)
	}
	reloaded, err := store.Definition(ctx, input.ID)
	if err != nil || !reflect.DeepEqual(input, reloaded) {
		t.Fatalf("frozen preparation differs: err=%v", err)
	}
	if created, err := store.Create(ctx, reloaded, now.Add(time.Second)); err != nil || created {
		t.Fatalf("preparation replay: created=%v err=%v", created, err)
	}
	changed := reloaded
	changed.PreparationFailure = &jobs.PreparationFailure{Code: "invalid_configuration", Diagnostic: "ConfigurationSpaceError: changed input"}
	if _, err := store.Create(ctx, changed, now); !errors.Is(err, jobs.ErrConflict) {
		t.Fatalf("changed frozen failure must conflict: %v", err)
	}
	// 同一任务不能既携带可执行模板/请求，又要求 worker 直接失败。
	changed.CoreTemplate = &jobs.FixedBattleTemplate{}
	if changed.Validate() == nil {
		t.Fatal("mixed template and preparation failure accepted")
	}
	changed = reloaded
	changed.Cases[0].CoreRequest = definition("unused", 1).Cases[0].CoreRequest
	if changed.Validate() == nil {
		t.Fatal("mixed case request and preparation failure accepted")
	}
	changed = input
	changed.PreparationFailure = &jobs.PreparationFailure{Code: "worker_crash", Diagnostic: "not an input preparation error"}
	if changed.Validate() == nil {
		t.Fatal("runtime error masqueraded as preparation failure")
	}
}
