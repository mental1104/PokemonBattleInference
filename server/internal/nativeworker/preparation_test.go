package nativeworker_test

import (
	"context"
	"pokemonbattleinference/server/internal/jobs"
	"testing"
)

// TestFrozenPreparationFailureRetainsOriginalAsyncContract 对照原逐case准备失败合同，禁止假计算或协调器级failed替代。
func TestFrozenPreparationFailureRetainsOriginalAsyncContract(t *testing.T) {
	store, _, options := database(t)
	value := definition("fixed-one-on-one-job-frozen-preparation", options.Revision, 3)
	value.Spec.ProcessCount = 2
	diagnostic := "ConfigurationSpaceError: unknown stat profile preset: no_investment"
	value.PreparationFailure = &jobs.PreparationFailure{Code: "invalid_configuration", Diagnostic: diagnostic}
	for index := range value.Cases {
		value.Cases[index].CoreRequest = nil
	}
	create(t, store, value)
	worked, err := workerFor(t, store, options).RunOnce(context.Background())
	if err != nil || !worked {
		t.Fatalf("worked=%v err=%v", worked, err)
	}
	header, err := store.Get(context.Background(), value.ID)
	if err != nil || header.Status != jobs.CompletedWithFailures || header.Counts.Failed != 3 ||
		header.Counts.Pending != 0 || header.Counts.Running != 0 || header.FailureCode != nil || header.Diagnostic != nil ||
		header.Counts.Nodes != 0 || header.Counts.Edges != 0 || header.Counts.Budget != 0 {
		t.Fatalf("preparation failure changed the original job summary: %+v err=%v", header, err)
	}
	for _, item := range value.Cases {
		result, err := store.Result(context.Background(), value.ID, item.PairID)
		if err != nil || result == nil || result.Status != jobs.Failed || result.FailureCode == nil ||
			*result.FailureCode != "invalid_configuration" || result.Diagnostic == nil || *result.Diagnostic != diagnostic ||
			result.Nodes != 0 || result.Edges != 0 || result.Budget != 0 || result.AttackerWin != nil ||
			result.DefenderWin != nil || result.Draw != nil || result.ExpectedTurns != nil || result.Explanation != nil {
			t.Fatalf("preparation failure fabricated a case result: %+v err=%v", result, err)
		}
	}
}
