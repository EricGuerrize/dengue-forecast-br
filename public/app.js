const state = {
  data: null,
  cityId: 5103403,
  horizon: 4,
  period: 52,
  query: "",
};
const $ = (id) => document.getElementById(id);
const int = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const one = new Intl.NumberFormat("pt-BR", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
});
const dateLabel = (iso) =>
  new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${iso}T12:00:00Z`));
const alertNames = {
  verde: "Abaixo da mediana",
  amarelo: "Entre mediana e p90",
  vermelho: "Acima do p90",
  sem_dado: "Sem dados",
};
const rank = { vermelho: 0, amarelo: 1, verde: 2, sem_dado: 3 };

function text(id, value) {
  $(id).textContent = value;
}
function city() {
  return (
    state.data.cities.find((item) => item.id === state.cityId) ||
    state.data.cities[0]
  );
}
function forecast(item) {
  return item.forecast[String(state.horizon)];
}
function format(value, fraction = false) {
  return value == null ? "—" : (fraction ? one : int).format(value);
}

function drawChart(item, prediction) {
  const history = item.history.slice(-state.period);
  if (!history.length) {
    $("chart").textContent = "Histórico indisponível.";
    return;
  }
  const width = 700,
    height = 300,
    left = 42,
    right = 22,
    top = 17,
    bottom = 35;
  const observedX = width - right - 92;
  const x = (index) =>
    left + (index / Math.max(1, history.length - 1)) * (observedX - left);
  const values = history.map((point) => point[1] || 0);
  if (prediction?.cases != null) values.push(prediction.cases);
  const maximum = Math.max(5, ...values) * 1.18;
  const y = (value) => top + (1 - value / maximum) * (height - top - bottom);
  const path = history
    .map(
      (point, index) =>
        `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point[1] || 0).toFixed(1)}`,
    )
    .join(" ");
  const grid = Array.from({ length: 4 }, (_, index) => {
    const value = (maximum * (3 - index)) / 3;
    const yy = y(value);
    return `<line x1="${left}" x2="${width - right}" y1="${yy}" y2="${yy}" stroke="#e6eeec"/><text x="${left - 8}" y="${yy + 4}" text-anchor="end">${int.format(value)}</text>`;
  }).join("");
  const last = history.at(-1);
  const targetX = width - right - 12;
  const forecastMark =
    prediction?.cases == null
      ? ""
      : `<circle cx="${targetX}" cy="${y(prediction.cases)}" r="7" fill="#b34f56" stroke="white" stroke-width="2"><title>${format(prediction.cases)} casos previstos em ${dateLabel(prediction.target)}</title></circle>`;
  const labels = [
    history[0],
    history[Math.floor((history.length - 1) / 2)],
    last,
  ];
  const labelX = [left, x(Math.floor((history.length - 1) / 2)), observedX];
  const ticks = labels
    .map(
      (point, index) =>
        `<text x="${labelX[index]}" y="${height - 8}" text-anchor="${index === 0 ? "start" : index === 2 ? "end" : "middle"}">${dateLabel(point[0])}</text>`,
    )
    .join("");
  $("chart").innerHTML =
    `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${grid}<line x1="${observedX}" y1="${top}" x2="${observedX}" y2="${height - bottom}" stroke="#9bb0ad" stroke-dasharray="5 5"/><path d="${path}" fill="none" stroke="#176c70" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="${observedX}" cy="${y(last[1] || 0)}" r="4.5" fill="#176c70"><title>${format(last[1])} casos em ${dateLabel(last[0])}</title></circle>${forecastMark}${ticks}</svg>`;
  $("chart").setAttribute(
    "aria-label",
    `Casos observados de ${dateLabel(history[0][0])} a ${dateLabel(last[0])}: ${format(last[1])} na última semana. Projeção de ${format(prediction?.cases)} casos para ${prediction ? dateLabel(prediction.target) : "sem data"}.`,
  );
}

function renderCity() {
  const item = city();
  state.cityId = item.id;
  $("city-select").value = String(item.id);
  const point = item.history.at(-1);
  const prediction = forecast(item);
  text("city-title", item.name);
  text("observed", format(point?.[1]));
  text(
    "observed-date",
    point ? `Semana de ${dateLabel(point[0])}` : "Sem dados",
  );
  text("nowcast", format(item.nowcast, true));
  text("prediction", format(prediction?.cases));
  text("prediction-period", `Modelo LightGBM · ${state.horizon} semanas`);
  text(
    "target-date",
    prediction
      ? `Semana prevista: ${dateLabel(prediction.target)} · origem: ${dateLabel(point[0])}`
      : "Previsão indisponível",
  );
  const level = prediction?.alert || "sem_dado";
  $("alert-badge").className = `alert-badge ${level}`;
  text("alert-badge", alertNames[level]);
  text("p50", format(prediction?.p50, true));
  text("p90", format(prediction?.p90, true));
  text("incidence", format(prediction?.incidence, true));
  text(
    "insight-copy",
    prediction
      ? `A incidência prevista para ${item.name} fica ${level === "vermelho" ? "acima do percentil 90" : level === "amarelo" ? "entre a mediana e o percentil 90" : "abaixo da mediana"} das semanas registradas no município.`
      : "Ainda não há previsão para este município.",
  );
  drawChart(item, prediction);
  const quality = item.quality[String(state.horizon)] || [];
  $("quality-table").innerHTML = quality.length
    ? quality
        .map(
          (row) =>
            `<div class="quality-row"><strong>${row.model}</strong><span>${format(row.mae, true)} casos · ${format(row.n)} previsões</span></div>`,
        )
        .join("")
    : '<p class="subtle">Sem avaliação disponível.</p>';
}

function renderList() {
  const levels = { verde: 0, amarelo: 0, vermelho: 0, sem_dado: 0 };
  const all = state.data.cities.map((item) => ({
    item,
    point: forecast(item),
  }));
  all.forEach(({ point }) => {
    levels[point?.alert || "sem_dado"] += 1;
  });
  $("state-summary").innerHTML = ["vermelho", "amarelo", "verde", "sem_dado"]
    .map(
      (level) =>
        `<span class="summary-chip ${level}">${levels[level]} · ${alertNames[level]}</span>`,
    )
    .join("");
  const filtered = all
    .filter(({ item }) =>
      item.name.toLocaleLowerCase("pt-BR").includes(state.query),
    )
    .sort(
      (a, b) =>
        rank[a.point?.alert || "sem_dado"] -
          rank[b.point?.alert || "sem_dado"] ||
        a.item.name.localeCompare(b.item.name, "pt-BR"),
    );
  const body = $("city-rows");
  body.replaceChildren();
  for (const { item, point } of filtered) {
    const row = document.createElement("tr");
    row.tabIndex = 0;
    if (item.id === state.cityId) row.className = "selected";
    const level = point?.alert || "sem_dado";
    const cells = [
      item.name,
      alertNames[level],
      format(point?.cases),
      format(point?.incidence, true),
      point ? dateLabel(point.target) : "—",
    ];
    cells.forEach((value, index) => {
      const cell = document.createElement("td");
      if (index === 1) {
        const badge = document.createElement("span");
        badge.className = `table-pill ${level}`;
        badge.textContent = value;
        cell.append(badge);
      } else cell.textContent = value;
      row.append(cell);
    });
    const select = () => {
      state.cityId = item.id;
      renderCity();
      renderList();
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    row.addEventListener("click", select);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
    body.append(row);
  }
  if (!filtered.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.textContent = "Nenhum município encontrado.";
    row.append(cell);
    body.append(row);
  }
}

function renderValidation() {
  const result = state.data.validation.find(
    (item) => item.horizon === state.horizon,
  );
  $("validation").innerHTML = result
    ? `<div class="validation-row"><span>Precisão da faixa vermelha</span><strong>${result.precision == null ? "—" : format(result.precision * 100, true) + "%"}</strong></div><div class="validation-row"><span>Sensibilidade</span><strong>${result.recall == null ? "—" : format(result.recall * 100, true) + "%"}</strong></div><div class="validation-row"><span>Previsões avaliadas</span><strong>${format(result.n)}</strong></div>`
    : '<p class="subtle">Validação indisponível neste recorte.</p>';
}

function render() {
  renderCity();
  renderList();
  renderValidation();
}
function setActive(group, attribute, value) {
  document.querySelectorAll(`[${attribute}]`).forEach((button) => {
    const active = Number(button.dataset[group]) === value;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

async function init() {
  try {
    const response = await fetch("/data/dashboard.json", { cache: "no-cache" });
    if (!response.ok)
      throw new Error(`Falha ao carregar os dados (${response.status}).`);
    state.data = await response.json();
    if (!state.data.cities?.length)
      throw new Error("O arquivo de dados está vazio.");
    const select = $("city-select");
    select.replaceChildren();
    state.data.cities.forEach((item) => {
      const option = document.createElement("option");
      option.value = String(item.id);
      option.textContent = item.name;
      select.append(option);
    });
    if (!state.data.cities.some((item) => item.id === state.cityId))
      state.cityId = state.data.cities[0].id;
    text("last-updated", `Última semana · ${dateLabel(state.data.lastWeek)}`);
    const age = Math.floor(
      (Date.now() - new Date(`${state.data.lastWeek}T12:00:00Z`).getTime()) /
        86400000,
    );
    if (age > 14) {
      $("freshness").hidden = false;
      $("freshness").textContent =
        `A última semana registrada foi há ${age} dias. As projeções partem desse recorte e não representam a situação atual.`;
    }
    render();
    select.addEventListener("change", () => {
      state.cityId = Number(select.value);
      renderCity();
      renderList();
    });
    $("city-search").addEventListener("input", (event) => {
      state.query = event.target.value.trim().toLocaleLowerCase("pt-BR");
      renderList();
    });
    document.querySelectorAll("[data-horizon]").forEach((button) =>
      button.addEventListener("click", () => {
        state.horizon = Number(button.dataset.horizon);
        setActive("horizon", "data-horizon", state.horizon);
        render();
      }),
    );
    document.querySelectorAll("[data-period]").forEach((button) =>
      button.addEventListener("click", () => {
        state.period = Number(button.dataset.period);
        setActive("period", "data-period", state.period);
        renderCity();
      }),
    );
  } catch (error) {
    $("error").hidden = false;
    $("error").textContent = error.message;
    text("last-updated", "Dados indisponíveis");
  }
}
init();
