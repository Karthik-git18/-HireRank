document.addEventListener("DOMContentLoaded", () => {
  const sidebar = document.getElementById("sidebar");
  document.getElementById("menuToggle")?.addEventListener("click", () => sidebar?.classList.toggle("sidebar-open"));

  document.querySelectorAll(".confirm-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm || "Are you sure?")) event.preventDefault();
    });
  });

  const fileInput = document.getElementById("resumeFiles");
  const fileList = document.getElementById("fileList");
  fileInput?.addEventListener("change", () => {
    fileList.replaceChildren();
    Array.from(fileInput.files).forEach((file) => {
      const row = document.createElement("div");
      row.className = "selected-file";
      const valid = file.name.toLowerCase().endsWith(".pdf") && file.size <= 5 * 1024 * 1024;
      row.innerHTML = `<i class="fa-regular fa-file-pdf"></i><span>${escapeHtml(file.name)}<small>${(file.size / 1024 / 1024).toFixed(2)} MB</small></span><i class="fa-solid ${valid ? "fa-circle-check text-success" : "fa-circle-exclamation text-danger"}"></i>`;
      fileList.appendChild(row);
    });
  });

  const suggestButton = document.getElementById("suggestSkills");
  suggestButton?.addEventListener("click", () => {
    const description = document.querySelector('[name="job_description"]')?.value || "";
    const skills = JSON.parse(suggestButton.dataset.skills || "[]");
    const matches = skills.filter((skill) => {
      const escaped = skill.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
      return new RegExp(`(^|[^\\w+#])${escaped}($|[^\\w+#])`, "i").test(description);
    });
    const field = document.querySelector('[name="required_skills"]');
    const existing = field.value.split(/[,;\n]+/).map((value) => value.trim()).filter(Boolean);
    field.value = Array.from(new Set([...existing, ...matches])).join(", ");
    field.dispatchEvent(new Event("input", { bubbles: true }));
    if (!matches.length) window.alert("No skills from HireRank's built-in catalog were found in the description.");
  });

  const analyzeButton = document.getElementById("analyzeDescription");
  const renderList = (list, items) => {
    list.innerHTML = "";
    if (!items || !items.length) {
      const item = document.createElement("li");
      item.textContent = "Not captured";
      list.appendChild(item);
      return;
    }
    items.forEach((entry) => {
      const item = document.createElement("li");
      item.textContent = entry;
      list.appendChild(item);
    });
  };

  analyzeButton?.addEventListener("click", async () => {
    const description = document.querySelector('[name="job_description"]')?.value || "";
    if (!description.trim()) {
      window.alert("Add a job description before running the analysis.");
      return;
    }
    let responseDetails = {};
    try {
      const csrfToken = document.querySelector('form.form-layout input[name="csrf_token"]')?.value;
      if (!csrfToken) {
        throw new Error("The security token is missing. Refresh the page and try again.");
      }
      const response = await fetch("/jobs/analyze", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ description }),
      });
      const contentType = response.headers.get("content-type") || "";
      const responseBody = await response.text();
      responseDetails = {
        status: response.status,
        statusText: response.statusText,
        contentType,
      };
      if (!contentType.toLowerCase().includes("application/json")) {
        responseDetails.body = responseBody.slice(0, 500);
        throw new Error(
          response.ok
            ? "The server returned an unexpected non-JSON response."
            : `The analysis request failed with HTTP ${response.status}. The server returned a non-JSON response.`,
        );
      }

      let payload;
      try {
        payload = JSON.parse(responseBody);
      } catch {
        responseDetails.body = responseBody.slice(0, 500);
        throw new Error("The server returned malformed JSON for the analysis request.");
      }
      responseDetails.payload = payload;
      if (!response.ok) {
        throw new Error(payload.message || `The analysis request failed with HTTP ${response.status}.`);
      }
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        throw new Error("The server returned an invalid analysis response.");
      }
      document.getElementById("analysisRole").textContent = payload.role || "Not specified";
      document.getElementById("analysisExperience").textContent = payload.minimum_experience !== null && payload.minimum_experience !== undefined ? `${payload.minimum_experience} years` : "Not specified";
      document.getElementById("analysisEducation").textContent = (payload.education_requirements || []).length ? payload.education_requirements.join(", ") : "Not specified";
      document.getElementById("analysisConfidence").textContent = payload.confidence ? payload.confidence.charAt(0).toUpperCase() + payload.confidence.slice(1) : "Low";
      renderList(document.getElementById("analysisRequiredSkills"), payload.required_skills || []);
      renderList(document.getElementById("analysisPreferredSkills"), payload.preferred_skills || []);
      renderList(document.getElementById("analysisKeywords"), payload.important_technical_keywords || []);
      renderList(document.getElementById("analysisSoftSkills"), payload.soft_skills || []);
      renderList(document.getElementById("analysisResponsibilities"), payload.job_responsibilities || []);
      const requiredField = document.querySelector('[name="required_skills"]');
      if (requiredField && requiredField.value.trim() === "") {
        requiredField.value = (payload.required_skills || []).join(", ");
      }
      const preferredField = document.querySelector('[name="preferred_skills"]');
      if (preferredField && preferredField.value.trim() === "") {
        preferredField.value = (payload.preferred_skills || []).join(", ");
      }
      const experienceField = document.querySelector('[name="required_experience"]');
      if (experienceField && (!experienceField.value || experienceField.value.trim() === "")) {
        const experience = payload.minimum_experience;
        experienceField.value = experience !== null && experience !== undefined ? String(experience) : "";
      }
      const educationField = document.querySelector('[name="education_requirement"]');
      if (educationField && (!educationField.value || educationField.value.trim() === "")) {
        const education = (payload.education_requirements || [])[0] || "";
        educationField.value = education;
      }
    } catch (error) {
      console.error("Job description analysis failed.", { ...responseDetails, error });
      window.alert(error instanceof Error ? error.message : "The description analysis failed. Please review the text and try again.");
    }
  });

  const candidateTable = document.getElementById("candidateTable");
  if (candidateTable) {
    const body = candidateTable.querySelector("tbody");
    const search = document.getElementById("candidateSearch");
    const skill = document.getElementById("skillFilter");
    const experience = document.getElementById("experienceFilter");
    const status = document.getElementById("statusFilter");
    const score = document.getElementById("scoreFilter");
    const sort = document.getElementById("sortOrder");
    const count = document.getElementById("candidateCount");
    const rows = Array.from(body.querySelectorAll("tr"));
    const filterRows = () => {
      const query = search.value.trim().toLowerCase();
      const minimum = Number(score.value);
      rows.forEach((row) => {
        row.hidden = !(row.dataset.search.includes(query)
          && (!skill.value.trim() || row.dataset.skills.includes(skill.value.trim().toLowerCase()))
          && (!experience.value || row.dataset.experience === experience.value)
          && (!status.value || row.dataset.status === status.value)
          && Number(row.dataset.score) >= minimum);
      });
      rows.filter((row) => !row.hidden).sort((a, b) => {
        const difference = Number(a.dataset.score) - Number(b.dataset.score);
        return sort.value === "asc" ? difference : -difference;
      }).forEach((row, index) => {
        row.querySelector(".rank-number").textContent = String(index + 1);
        body.appendChild(row);
      });
      count.textContent = `${rows.filter((row) => !row.hidden).length} candidates`;
    };
    [search, skill, experience, status, score, sort].forEach((element) => element.addEventListener("input", filterRows));
    const checks = Array.from(document.querySelectorAll(".compare-check"));
    const button = document.getElementById("compareButton");
    const updateCompare = () => {
      const selected = checks.filter((check) => check.checked);
      button.disabled = selected.length < 2 || selected.length > 5;
      checks.forEach((check) => { check.disabled = !check.checked && selected.length >= 5; });
      button.textContent = `Compare selected (${selected.length}/5)`;
    };
    checks.forEach((check) => check.addEventListener("change", updateCompare));
  }

  const statusSelect = document.getElementById("candidateStatus");
  const reasonField = document.getElementById("rejectionReasonField");
  const updateReason = () => {
    if (statusSelect && reasonField) reasonField.hidden = statusSelect.value !== "Rejected";
  };
  statusSelect?.addEventListener("change", updateReason);
  updateReason();
});

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[character]);
}

window.HireRankCharts = {
  line(id, labels, values) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    new Chart(canvas, {
      type: "line",
      data: { labels, datasets: [{ label: "Applications", data: values, borderColor: "#6756d8",
        backgroundColor: "rgba(103,86,216,.10)", fill: true, tension: .35, pointRadius: 3 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, x: { grid: { display: false } } } },
    });
  },
  doughnut(id, labels, values) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    new Chart(canvas, {
      type: "doughnut",
      data: { labels, datasets: [{ data: values, backgroundColor: ["#6756d8", "#3b82f6", "#f59e0b",
        "#22a06b", "#ed6a5a", "#8b9bb4"], borderWidth: 0, hoverOffset: 4 }] },
      options: { maintainAspectRatio: false, cutout: "70%", plugins: { legend: { display: false } } },
    });
  },
};
