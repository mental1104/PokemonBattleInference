package httpapi_test

import (
	"context"
	"encoding/json"
	"fmt"
	"pokemonbattleinference/server/internal/httpapi"
	"pokemonbattleinference/server/internal/jobs"
	"testing"
	"time"
)

// TestJobsHTTPPostgres 从真实 PG 任务状态验证原列表/详情/取消协议，取消不伪造已完成。
func TestJobsHTTPPostgres(t *testing.T) {
	db := isolatedDatabase(t)
	store := jobs.New(db)
	if err := store.Migrate(context.Background()); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	spec := jobs.ExecutionSpec{ContractVersion: "one-on-one-move-pool.v1", WeightAssumption: "uniform_configuration_pair", AttackerPolicy: "first-legal-action", DefenderPolicy: "uniform-random", MechanismAdmission: "supported_only", ProcessCount: 1, QueueDepth: 1, MaxNodes: 100, MaxEdges: 400}
	for index, id := range []string{"fixed-one-on-one-job-a", "configuration-job-b", "fixed-one-on-one-job-c"} {
		definition := jobs.Definition{ID: id, RulesetID: "pokemon-champion", VersionGroupID: 25, Revision: "test-revision", Spec: spec}
		for n := 0; n < 2; n++ {
			definition.Cases = append(definition.Cases, jobs.CaseDefinition{PairID: fmt.Sprintf("pair-%d", n), AttackerID: "a", DefenderID: "b", AttackerMoves: []int{1}, DefenderMoves: []int{2}, CoreRequest: json.RawMessage(`{"schema_version":1,"operations":[{"kind":"hp","base":91,"iv":31,"ev":0,"level":50}]}`)})
		}
		if _, err := store.Create(context.Background(), definition, now.Add(time.Duration(index)*time.Millisecond)); err != nil {
			t.Fatal(err)
		}
	}
	handler := httpapi.NewServer(db)
	got := request(t, handler, "GET", "/v1/inference/jobs?job_type=fixed-one-on-one&limit=2", "", "")
	var page struct {
		Items []struct {
			JobID string `json:"job_id"`
			Type  string `json:"job_type"`
			Phase string `json:"phase"`
		} `json:"items"`
		Cursor *string `json:"next_cursor"`
	}
	if err := json.Unmarshal(got.Body.Bytes(), &page); err != nil {
		t.Fatal(err)
	}
	if got.Code != 200 || len(page.Items) != 2 || page.Items[0].JobID != "fixed-one-on-one-job-c" || page.Items[1].JobID != "fixed-one-on-one-job-a" || page.Items[0].Type != "fixed-one-on-one" || page.Items[0].Phase != "queued" || page.Cursor == nil || *page.Cursor != "2" {
		t.Fatalf("job page status=%d body=%s", got.Code, got.Body)
	}
	job, err := store.ClaimJob(context.Background(), "coordinator", "test-revision", now, time.Minute)
	if err != nil || job == nil {
		t.Fatalf("claim job err=%v", err)
	}
	cases, err := store.ClaimCases(context.Background(), job.ID, "worker", "test-revision", now, time.Minute, 1)
	if err != nil || len(cases) != 1 {
		t.Fatalf("claim cases err=%v", err)
	}
	_, err = store.RecordProgress(context.Background(), job.ID, cases[0].Definition.PairID, "worker", "test-revision", now, jobs.Progress{Phase: "building_graph", ObservedNodes: 25, ObservedEdges: 40, ExpandedNodes: 20, Frontier: 5})
	if err != nil {
		t.Fatal(err)
	}
	path := "/v1/inference/jobs/" + job.ID
	got = request(t, handler, "GET", path, "", "")
	var detail struct {
		Status    string `json:"status"`
		CanCancel bool   `json:"can_cancel"`
		Progress  struct {
			Counts struct {
				Running   int `json:"running"`
				Pending   int `json:"pending"`
				Completed int `json:"completed"`
			} `json:"counts"`
			Running struct {
				ID      string  `json:"configuration_id"`
				Percent float64 `json:"percent"`
				Phase   string  `json:"phase"`
			} `json:"running_case"`
		} `json:"progress"`
	}
	if err = json.Unmarshal(got.Body.Bytes(), &detail); err != nil {
		t.Fatal(err)
	}
	if got.Code != 200 || detail.Status != "running" || !detail.CanCancel || detail.Progress.Counts.Running != 1 || detail.Progress.Counts.Pending != 1 || detail.Progress.Counts.Completed != 0 || detail.Progress.Running.Percent != 25 || detail.Progress.Running.Phase != "building_graph" {
		t.Fatalf("running detail status=%d body=%s", got.Code, got.Body)
	}
	got = request(t, handler, "POST", path+"/cancel", "", "")
	var cancelled struct {
		Job struct {
			Status      string `json:"status"`
			RequestedAt string `json:"cancel_requested_at"`
		} `json:"job"`
	}
	if err = json.Unmarshal(got.Body.Bytes(), &cancelled); err != nil {
		t.Fatal(err)
	}
	if got.Code != 200 || cancelled.Job.Status != "cancel_requested" || cancelled.Job.RequestedAt == "" {
		t.Fatalf("cancel status=%d body=%s", got.Code, got.Body)
	}
	first := cancelled.Job.RequestedAt
	got = request(t, handler, "POST", path+"/cancel", "", "")
	if err = json.Unmarshal(got.Body.Bytes(), &cancelled); err != nil || cancelled.Job.RequestedAt != first {
		t.Fatalf("cancel replay changed timestamp body=%s err=%v", got.Body, err)
	}
	if count, e := store.CancelUnclaimed(context.Background(), job.ID, now.Add(2*time.Minute)); e != nil || count != 2 {
		t.Fatalf("cancel cases count=%d err=%v", count, e)
	}
	if _, err = store.Finalize(context.Background(), job.ID, now.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}
	got = request(t, handler, "GET", path, "", "")
	if err = json.Unmarshal(got.Body.Bytes(), &detail); err != nil || got.Code != 200 || detail.Status != "cancelled" || detail.CanCancel {
		t.Fatalf("cancelled detail status=%d body=%s err=%v", got.Code, got.Body, err)
	}
	for _, path := range []string{"/v1/inference/jobs?status=unknown", "/v1/inference/jobs?cursor=-1", "/v1/inference/jobs?job_type=unknown"} {
		if got = request(t, handler, "GET", path, "", ""); got.Code != 422 {
			t.Fatalf("invalid job query path=%s status=%d", path, got.Code)
		}
	}
	if got = request(t, handler, "GET", "/v1/inference/jobs/missing", "", ""); got.Code != 404 {
		t.Fatalf("missing job status=%d", got.Code)
	}
}
