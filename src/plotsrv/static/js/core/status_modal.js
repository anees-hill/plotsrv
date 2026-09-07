(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const state = window.PLOTSRV.state;
  const config = window.PLOTSRV.config;
  const AUTO_RANGES = [900, 3600, 21600, 86400, 604800];
  const STREAM_RANGE_MIN_TOLERANCE_MS = 10000;
  const STREAM_RANGE_MAX_TOLERANCE_MS = 120000;

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function setAttribute(id, name, value) {
    const element = document.getElementById(id);
    if (element) element.setAttribute(name, value);
  }

  function formatDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return "Not configured";
    if (value < 60) return value + " second" + (value === 1 ? "" : "s");
    if (value < 3600) {
      const minutes = Math.round(value / 60);
      return minutes + " minute" + (minutes === 1 ? "" : "s");
    }
    if (value < 86400) {
      const hours = Math.round(value / 3600);
      return hours + " hour" + (hours === 1 ? "" : "s");
    }
    const days = Math.round(value / 86400);
    return days + " day" + (days === 1 ? "" : "s");
  }

  function relativeTime(iso) {
    const milliseconds = Date.parse(iso || "");
    if (!Number.isFinite(milliseconds)) return "Unknown";
    if (Math.max(0, Date.now() - milliseconds) < 10000) return "Just now";
    return String(core.fmtAgo(iso) || core.fmtLocalTime(iso)).replace(/^\(|\)$/g, "");
  }

  function validActivityEvents(payload) {
    const activity = payload && payload.data_activity;
    const events = activity && Array.isArray(activity.events) ? activity.events : [];
    return events
      .map(function (event) {
        const time = Date.parse(event && event.received_at);
        const count = Number(event && event.count);
        return {
          time: time,
          receivedAt: event && event.received_at,
          count: Number.isSafeInteger(count) && count > 0 ? count : 1,
          source: event && event.source,
        };
      })
      .filter(function (event) {
        return Number.isFinite(event.time);
      })
      .sort(function (left, right) {
        return left.time - right.time;
      });
  }

  function autoRangeSeconds(events, now) {
    if (!events.length) return 3600;
    const spanSeconds = Math.max(1, Math.ceil((now - events[0].time) / 1000));
    for (const seconds of AUTO_RANGES) {
      if (spanSeconds <= seconds) return seconds;
    }
    return null;
  }

  function formatAxisTime(milliseconds, rangeMilliseconds) {
    const date = new Date(milliseconds);
    if (!Number.isFinite(date.getTime())) return "—";
    if (rangeMilliseconds <= 86400000) {
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function streamRangeTolerance(events) {
    const gaps = [];
    for (let index = 1; index < events.length; index += 1) {
      const gap = events[index].time - events[index - 1].time;
      if (Number.isFinite(gap) && gap > 0) gaps.push(gap);
    }
    if (!gaps.length) return STREAM_RANGE_MIN_TOLERANCE_MS;
    gaps.sort(function (left, right) { return left - right; });
    const middle = Math.floor(gaps.length / 2);
    const median = gaps.length % 2
      ? gaps[middle]
      : (gaps[middle - 1] + gaps[middle]) / 2;
    return Math.max(
      STREAM_RANGE_MIN_TOLERANCE_MS,
      Math.min(STREAM_RANGE_MAX_TOLERANCE_MS, median * 3)
    );
  }

  function streamActivityRanges(events) {
    if (!events.length) return [];
    const tolerance = streamRangeTolerance(events);
    const ranges = [];
    let current = null;
    events.forEach(function (event) {
      if (!current || event.time - current.end > tolerance) {
        current = {
          start: event.time,
          end: event.time,
          startReceivedAt: event.receivedAt,
          endReceivedAt: event.receivedAt,
          batches: 1,
          count: event.count,
        };
        ranges.push(current);
        return;
      }
      current.end = event.time;
      current.endReceivedAt = event.receivedAt;
      current.batches += 1;
      current.count += event.count;
    });
    return ranges;
  }

  function streamRangeLabel(range) {
    const records = range.count + " accepted stream record" +
      (range.count === 1 ? "" : "s");
    const batches = range.batches + " batch" + (range.batches === 1 ? "" : "es");
    return records + " across " + batches + " · " +
      core.fmtLocalTime(range.startReceivedAt) + " – " +
      core.fmtLocalTime(range.endReceivedAt);
  }

  function renderArrivalTimeline(payload) {
    const track = document.getElementById("status-modal-activity-dots");
    const empty = document.getElementById("status-modal-activity-empty");
    const detail = document.getElementById("status-modal-activity-hover");
    const rangeSelect = document.getElementById("status-modal-range");
    const chart = track && track.closest(".ps-arrival-chart");
    if (!track || !empty || !rangeSelect) return;

    const events = validActivityEvents(payload);
    const now = Date.now();
    const selected = String(rangeSelect.value || "auto");
    const automatic = selected === "auto" ? autoRangeSeconds(events, now) : null;
    const seconds = selected === "all" ? null : selected === "auto"
      ? automatic
      : Number(selected);
    let start = seconds === null
      ? events.length ? events[0].time : now - 3600000
      : now - seconds * 1000;
    if (start >= now) start = now - 1000;
    const visible = events.filter(function (event) {
      return event.time >= start && event.time <= now + 1000;
    });

    track.replaceChildren();
    const streamRanges = config.kind === "stream" ? streamActivityRanges(visible) : [];
    if (config.kind === "stream") {
      streamRanges.forEach(function (range) {
        const segment = document.createElement("span");
        const startPosition = Math.max(0, Math.min(100, ((range.start - start) / (now - start)) * 100));
        const endPosition = Math.max(0, Math.min(100, ((range.end - start) / (now - start)) * 100));
        const width = Math.max(0.9, endPosition - startPosition);
        const label = streamRangeLabel(range);
        segment.className = "ps-arrival-chart__range";
        segment.style.left = Math.min(100 - width, startPosition) + "%";
        segment.style.width = width + "%";
        segment.title = label;
        segment.tabIndex = 0;
        segment.setAttribute("aria-label", label);
        if (detail) {
          const showDetail = function () { detail.textContent = label; };
          segment.addEventListener("mouseenter", showDetail);
          segment.addEventListener("focus", showDetail);
        }
        track.appendChild(segment);
      });
      if (detail) {
        detail.hidden = streamRanges.length === 0;
        detail.textContent = streamRanges.length
          ? "Hover over or focus an activity range for its start and end time."
          : "";
      }
    } else {
      visible.forEach(function (event, index) {
        const dot = document.createElement("span");
        const position = Math.max(1.5, Math.min(98.5, ((event.time - start) / (now - start)) * 100));
        const size = Math.min(13, 6 + Math.log2(event.count));
        dot.className = "ps-arrival-chart__dot";
        dot.style.left = position + "%";
        dot.style.width = size + "px";
        dot.style.height = size + "px";
        dot.style.bottom = 13 + (index % 3) * 9 + "px";
        dot.title = "Published update · " + core.fmtLocalTime(event.receivedAt);
        dot.setAttribute("aria-hidden", "true");
        track.appendChild(dot);
      });
      if (detail) {
        detail.hidden = true;
        detail.textContent = "";
      }
    }

    empty.hidden = visible.length !== 0;
    const rangeMilliseconds = now - start;
    setText("status-modal-range-start", formatAxisTime(start, rangeMilliseconds));
    setText("status-modal-range-end", formatAxisTime(now, rangeMilliseconds));
    if (chart) {
      const visibleItems = config.kind === "stream" ? streamRanges.length : visible.length;
      const itemName = config.kind === "stream" ? "stream activity range" : "data arrival event";
      chart.setAttribute(
        "aria-label",
        visibleItems + " " + itemName + (visibleItems === 1 ? "" : "s") +
          " in the selected time range."
      );
    }
  }

  function renderPolicy(freshness, historical) {
    const values = document.getElementById("status-modal-policy-values");
    if (!values) return;
    values.replaceChildren();
    if (!freshness || freshness.enabled === false) {
      setText(
        "status-modal-policy-copy",
        freshness && freshness.reason === "watch_source_without_view_freshness"
          ? "This watched source has no view-specific freshness policy."
          : "Freshness monitoring is disabled for this view."
      );
      return;
    }

    setText(
      "status-modal-policy-copy",
      historical
        ? "These thresholds apply to latest data, not the selected historical view."
        : "Age is evaluated locally as time passes, without polling the server."
    );
    const entries = [
      ["Expected interval", freshness.expected_every_s],
      ["Stale after", freshness.warn_after_s],
      ["Very stale after", freshness.overdue_after_s ?? freshness.error_after_s],
    ];
    entries.forEach(function (entry) {
      const wrap = document.createElement("div");
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = entry[0];
      description.textContent = formatDuration(entry[1]);
      wrap.appendChild(term);
      wrap.appendChild(description);
      values.appendChild(wrap);
    });
  }

  function renderStreamStatus(payload, historical) {
    const section = document.getElementById("status-modal-stream");
    if (!section) return;
    const stream = payload && payload.stream_status;
    section.hidden = config.kind !== "stream";
    if (section.hidden) return;

    const lifecycle = String((stream && stream.lifecycle) || "unknown");
    const lifecycleLabels = {
      live: "Live producer connection",
      retrying: "Producer retrying delivery",
      disconnected: "Producer disconnected",
      incomplete: "Disconnected with pending delivery",
      ended: "Producer ended",
    };
    setText("status-modal-stream-lifecycle", lifecycleLabels[lifecycle] || "Unknown");
    setText(
      "status-modal-stream-heartbeat",
      stream && stream.last_heartbeat_at
        ? relativeTime(stream.last_heartbeat_at)
        : "Not observed"
    );

    let continuity = "Not reported";
    if (stream) {
      if (stream.continuity_warning) continuity = String(stream.continuity_warning);
      else if (stream.source_available === false) continuity = "Source unavailable";
      else if (stream.source_transition === "replaced") continuity = "Source replaced; continuity uncertain";
      else if (stream.source_transition === "truncated") continuity = "Source truncated; continuity uncertain";
      else if (stream.source_available === true) continuity = "No known continuity gap";
    }
    setText("status-modal-stream-continuity", continuity);

    if (historical) {
      setText("status-modal-freshness", "Stored session");
      setText(
        "status-modal-freshness-detail",
        "This fixed session does not represent the current producer state."
      );
      return;
    }

    const summaryLabels = {
      live: "Active",
      retrying: "Retrying",
      disconnected: "Disconnected",
      incomplete: "Incomplete",
      ended: "Ended",
    };
    setText("status-modal-freshness", summaryLabels[lifecycle] || "Connecting");
    setText(
      "status-modal-freshness-detail",
      stream && stream.last_heartbeat_at
        ? "Last producer heartbeat " + relativeTime(stream.last_heartbeat_at) + "."
        : "Waiting for the first producer heartbeat."
    );
  }

  function renderStatusModal() {
    const modal = document.getElementById("status-modal");
    if (!modal || !state.statusModalOpen) return;
    const payload = state.latestStatusPayload || {};
    const snapshot = state.currentSnapshot;
    const historicalStream = state.streamHistoricalSessionId;
    const historical = !!snapshot || !!historicalStream;
    const snapshotMeta = typeof core.currentHistoryMeta === "function"
      ? core.currentHistoryMeta()
      : null;
    const streamView = config.kind === "stream";
    const policy = document.getElementById("status-modal-policy");

    setText("status-modal-title", streamView ? "Stream status" : "Live data status");
    setText(
      "status-modal-intro",
      streamView
        ? "What plotsrv and this browser currently know about this stream."
        : "What plotsrv and this browser currently know about this view."
    );
    setAttribute(
      "status-modal-close-icon",
      "aria-label",
      streamView ? "Close stream status" : "Close live data status"
    );
    setText("status-modal-viewing-label", streamView ? "Session" : "Viewing");
    setText(
      "status-modal-received-label",
      streamView ? "Last records received" : "Last data received"
    );
    setText("status-modal-browser-label", streamView ? "Browser stream" : "Browser view");
    setText("status-modal-freshness-label", streamView ? "Producer state" : "Freshness");
    setText(
      "status-modal-activity-title",
      streamView ? "Records received over time" : "Data received over time"
    );
    if (policy) policy.hidden = streamView;

    if (snapshot) {
      setText("status-modal-viewing", "Snapshot");
      setText(
        "status-modal-viewing-detail",
        snapshotMeta && snapshotMeta.created_at
          ? "Saved " + core.fmtLocalTime(snapshotMeta.created_at) + "."
          : "A fixed historical snapshot is selected."
      );
    } else if (historicalStream) {
      setText("status-modal-viewing", "Stored stream session");
      setText("status-modal-viewing-detail", "A bounded historical observation is selected.");
    } else if (streamView) {
      setText("status-modal-viewing", "Current stream");
      setText("status-modal-viewing-detail", "This browser follows the active observation.");
    } else {
      setText("status-modal-viewing", "Latest data");
      setText("status-modal-viewing-detail", "This view follows accepted live updates.");
    }

    const lastArrival = payload.last_data_arrival_at;
    if (lastArrival) {
      setText("status-modal-received", relativeTime(lastArrival));
      setText("status-modal-received-detail", core.fmtLocalTime(lastArrival));
    } else if (payload.restored_from_storage && payload.last_updated) {
      setText("status-modal-received", "Before this process started");
      setText(
        "status-modal-received-detail",
        "Stored update timestamp: " + core.fmtLocalTime(payload.last_updated)
      );
    } else {
      setText("status-modal-received", "Not yet");
      setText("status-modal-received-detail", "No process-lifetime data arrival recorded.");
    }

    const waiting = state.headerStatus.browserData === "update_available";
    setText("status-modal-browser", waiting ? "Newer update waiting" : "Current");
    setText(
      "status-modal-browser-detail",
      waiting
        ? historical
          ? "Latest data has changed; the historical selection remains fixed."
          : state.streamPaused
            ? "Live table updates are paused. Resume them to apply the newest stream data."
            : "The server has newer data that this browser has not applied."
        : state.browserLastAppliedAt
          ? "Last applied " + relativeTime(state.browserLastAppliedAt) + "."
          : "The application time is not yet known."
    );

    const freshness = payload.freshness || state.headerStatus.latestData.freshness;
    if (!streamView) {
      if (historical) {
        setText("status-modal-freshness", "Not evaluated for history");
        setText("status-modal-freshness-detail", "Freshness applies only to latest data.");
      } else if (!freshness || freshness.enabled === false) {
        setText("status-modal-freshness", "Not configured");
        setText("status-modal-freshness-detail", "No active freshness policy applies.");
      } else {
        setText("status-modal-freshness", String(freshness.label || "Unknown"));
        setText(
          "status-modal-freshness-detail",
          typeof freshness.age_s === "number"
            ? "Latest data is " + core.formatAgeShort(freshness.age_s) + "."
            : "Waiting for the first relevant data arrival."
        );
      }
      renderPolicy(freshness, historical);
    }
    renderStreamStatus(payload, historical);

    const activity = payload.data_activity || {};
    setText(
      "status-modal-activity-copy",
      config.kind === "stream"
        ? "Nearby accepted record batches are combined into activity ranges; brief quiet gaps are tolerated and heartbeats are excluded."
        : "Each dot represents a published update received by plotsrv."
    );
    setText("status-modal-view-id", config.activeViewId);
    setText(
      "status-modal-source",
      payload.data_source && payload.data_source.label
        ? String(payload.data_source.label)
        : "Not known"
    );
    setText(
      "status-modal-applied",
      state.browserLastAppliedAt ? core.fmtLocalTime(state.browserLastAppliedAt) : "Not known"
    );
    const eventCount = Number(activity.event_count) || 0;
    const itemCount = Number(activity.represented_item_count) || 0;
    setText(
      "status-modal-retained",
      config.kind === "stream"
        ? eventCount + " batch event" + (eventCount === 1 ? "" : "s") +
          " representing " + itemCount + " record" + (itemCount === 1 ? "" : "s")
        : eventCount + " update event" + (eventCount === 1 ? "" : "s") +
          " (maximum " + (activity.limit || 256) + ")"
    );
    renderArrivalTimeline(payload);

    const updateNow = document.getElementById("status-modal-update-now");
    const returnLatest = document.getElementById("status-modal-return-latest");
    if (updateNow) updateNow.hidden = !waiting || historical || state.streamPaused;
    if (returnLatest) {
      returnLatest.hidden = !historical;
      returnLatest.textContent = waiting ? "Return to latest update" : "Return to latest";
    }
  }

  function focusableElements(modal) {
    return Array.from(
      modal.querySelectorAll(
        "button:not([disabled]):not([hidden]), select:not([disabled]), " +
          "summary, [href], [tabindex]:not([tabindex='-1'])"
      )
    ).filter(function (element) {
      return !element.closest("[hidden]");
    });
  }

  function openStatusModal() {
    const backdrop = document.getElementById("status-modal-backdrop");
    const close = document.getElementById("status-modal-close-icon");
    const button = document.getElementById("header-status-button");
    if (!backdrop) return;
    state.statusModalReturnFocus = document.activeElement;
    state.statusModalOpen = true;
    backdrop.hidden = false;
    if (document.body) document.body.classList.add("ps-status-modal-open");
    if (button) button.setAttribute("aria-expanded", "true");
    renderStatusModal();
    if (config.kind === "stream" && typeof core.refreshStatus === "function") {
      core.refreshStatus();
    }
    if (close) close.focus();
  }

  function closeStatusModal(options) {
    const backdrop = document.getElementById("status-modal-backdrop");
    const button = document.getElementById("header-status-button");
    if (!backdrop || backdrop.hidden) return;
    backdrop.hidden = true;
    state.statusModalOpen = false;
    if (document.body) document.body.classList.remove("ps-status-modal-open");
    if (button) button.setAttribute("aria-expanded", "false");
    if (!options || options.restoreFocus !== false) {
      const target = state.statusModalReturnFocus;
      if (target && typeof target.focus === "function") target.focus();
      else if (button) button.focus();
    }
  }

  function markBrowserViewApplied() {
    state.browserLastAppliedAt = new Date().toISOString();
    renderStatusModal();
  }

  function bindStatusModal() {
    const backdrop = document.getElementById("status-modal-backdrop");
    const modal = document.getElementById("status-modal");
    if (!backdrop || !modal || backdrop.dataset.plotsrvBound === "1") return;

    ["status-modal-close-icon", "status-modal-close"].forEach(function (id) {
      const button = document.getElementById(id);
      if (button) button.addEventListener("click", function () { closeStatusModal(); });
    });
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) closeStatusModal();
    });
    const range = document.getElementById("status-modal-range");
    if (range) range.addEventListener("change", renderStatusModal);

    const updateNow = document.getElementById("status-modal-update-now");
    if (updateNow) {
      updateNow.addEventListener("click", function () {
        if (typeof core.applyPendingUpdate !== "function") return;
        updateNow.disabled = true;
        const finish = function () {
          updateNow.disabled = false;
          renderStatusModal();
        };
        Promise.resolve(core.applyPendingUpdate({ force: true })).then(finish, finish);
      });
    }
    const returnLatest = document.getElementById("status-modal-return-latest");
    if (returnLatest) {
      returnLatest.addEventListener("click", function () {
        closeStatusModal();
        if (state.streamHistoricalSessionId && typeof core.returnToCurrentStream === "function") {
          core.returnToCurrentStream();
        } else if (typeof core.returnToLive === "function") {
          core.returnToLive();
        }
      });
    }

    modal.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeStatusModal();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = focusableElements(modal);
      if (!focusable.length) {
        event.preventDefault();
        modal.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    backdrop.dataset.plotsrvBound = "1";
  }

  core.renderStatusModal = renderStatusModal;
  core.openStatusModal = openStatusModal;
  core.closeStatusModal = closeStatusModal;
  core.markBrowserViewApplied = markBrowserViewApplied;
  core.bindStatusModal = bindStatusModal;
})();
