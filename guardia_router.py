// NuevaConsultaModal.jsx — De Guardia con adjuntos clínicos anonimizados
import React, { useEffect, useState } from "react";

const API =
  import.meta.env.VITE_API_URL || "https://galenos-backend.onrender.com";

export default function NuevaConsultaModal({ onClose, onCreated }) {
  const token = localStorage.getItem("galenos_token");

  const [title, setTitle] = useState("");
  const [original, setOriginal] = useState("");
  const [patientId, setPatientId] = useState("");

  const [attachments, setAttachments] = useState([]);
  const [options, setOptions] = useState({ analytics: [], imaging: [] });

  const [loadingOptions, setLoadingOptions] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // ==========================
  // Cargar adjuntos disponibles
  // ==========================
  useEffect(() => {
    if (!patientId) {
      setOptions({ analytics: [], imaging: [] });
      return;
    }

    const loadOptions = async () => {
      setLoadingOptions(true);
      try {
        const res = await fetch(
          `${API}/guard/attachments/options?patient_id=${patientId}`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        const data = await res.json();
        setOptions(data);
      } catch {
        // silencioso
      } finally {
        setLoadingOptions(false);
      }
    };

    loadOptions();
  }, [patientId, token]);

  const toggleAttachment = (kind, id) => {
    setAttachments((prev) => {
      const exists = prev.find((a) => a.kind === kind && a.id === id);
      if (exists) return prev.filter((a) => !(a.kind === kind && a.id === id));
      return [...prev, { kind, id }];
    });
  };

  // ==========================
  // Enviar consulta
  // ==========================
  const submit = async () => {
    setError("");

    if (!title.trim() || !original.trim()) {
      setError("Título y texto son obligatorios.");
      return;
    }

    try {
      setSubmitting(true);
      const res = await fetch(`${API}/guard/cases`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          title,
          original,
          patient_id: patientId || null,
          attachments,
        }),
      });

      if (!res.ok) {
        setError("No se pudo crear la consulta.");
        return;
      }

      onCreated && onCreated();
      onClose();
    } catch {
      setError("Error de conexión.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal">
      <h2 className="text-lg font-semibold mb-2">Nueva consulta de diagnóstico</h2>

      {error && <p className="text-sm text-red-600 mb-2">{error}</p>}

      <input
        className="sr-input w-full mb-2"
        placeholder="Título"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />

      <textarea
        className="sr-input w-full min-h-[120px] mb-2"
        placeholder="Describe el caso clínico (sin datos identificativos)..."
        value={original}
        onChange={(e) => setOriginal(e.target.value)}
      />

      <input
        className="sr-input w-full mb-2"
        placeholder="ID interno del paciente (opcional)"
        value={patientId}
        onChange={(e) => setPatientId(e.target.value)}
      />

      {loadingOptions && (
        <p className="text-xs text-gray-500">Cargando adjuntos clínicos…</p>
      )}

      {patientId && (
        <div className="border rounded p-2 text-xs space-y-2 mb-2">
          <p className="font-semibold">Adjuntar apoyo clínico (anonimizado)</p>

          {options.analytics.length > 0 && (
            <div>
              <p className="font-medium">Analíticas</p>
              {options.analytics.map((a) => (
                <label key={a.id} className="flex gap-2">
                  <input
                    type="checkbox"
                    onChange={() => toggleAttachment("analytic", a.id)}
                  />
                  {a.exam_date || "sin fecha"} — {a.summary.slice(0, 60)}…
                </label>
              ))}
            </div>
          )}

          {options.imaging.length > 0 && (
            <div>
              <p className="font-medium">Imágenes</p>
              {options.imaging.map((i) => (
                <label key={i.id} className="flex gap-2">
                  <input
                    type="checkbox"
                    onChange={() => toggleAttachment("imaging", i.id)}
                  />
                  {i.type} — {i.summary.slice(0, 60)}…
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="sr-btn-secondary text-xs">
          Cancelar
        </button>
        <button
          onClick={submit}
          disabled={submitting}
          className="sr-btn-primary text-xs"
        >
          {submitting ? "Publicando…" : "Publicar consulta"}
        </button>
      </div>
    </div>
  );
}
