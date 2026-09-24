import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Mic, MicOff, Square, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";

const subscribeCapabilities = () => () => {};
const noCapability = () => false;
const speechRecognitionAvailable = () =>
  !!(
    (window as SpeechWindow).SpeechRecognition ||
    (window as SpeechWindow).webkitSpeechRecognition
  );
const speechSynthesisAvailable = () => "speechSynthesis" in window;

type SpeechResult = {
  isFinal: boolean;
  [index: number]: { transcript: string };
};
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult:
    | ((event: {
        resultIndex: number;
        results: ArrayLike<SpeechResult>;
      }) => void)
    | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};

export function Dictation({
  onText,
  disabled,
}: {
  onText: (text: string) => void;
  disabled?: boolean;
}) {
  const available = useSyncExternalStore(
    subscribeCapabilities,
    speechRecognitionAvailable,
    noCapability,
  );
  const [listening, setListening] = useState(false);
  const [status, setStatus] = useState("");
  const [interim, setInterim] = useState("");
  const recognition = useRef<Recognition | null>(null);
  const callback = useRef(onText);
  useEffect(() => {
    callback.current = onText;
  }, [onText]);
  useEffect(() => {
    const scope = window as SpeechWindow;
    const Constructor =
      scope.SpeechRecognition || scope.webkitSpeechRecognition;
    if (!Constructor) return;
    const instance = new Constructor();
    instance.lang = "es-ES";
    instance.continuous = true;
    instance.interimResults = true;
    instance.onresult = (event) => {
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) callback.current(result[0].transcript);
        else pending += result[0].transcript;
      }
      setInterim(pending);
    };
    instance.onerror = ({ error }) => {
      const messages: Record<string, string> = {
        "not-allowed": "Permite el micrófono en el navegador para dictar.",
        "audio-capture": "No se detectó un micrófono disponible.",
        network:
          "El servicio de voz del navegador no responde. Revisa la conexión.",
        "no-speech": "No se detectó voz. Puedes volver a intentarlo.",
        "service-not-allowed":
          "Este navegador ha bloqueado su servicio de voz.",
      };
      if (error !== "aborted")
        setStatus(messages[error] || "No se pudo iniciar el dictado.");
      setListening(false);
    };
    instance.onend = () => {
      setListening(false);
      setInterim("");
    };
    recognition.current = instance;
    return () => {
      instance.onresult = null;
      instance.onerror = null;
      instance.onend = null;
      instance.abort();
    };
  }, []);
  useEffect(() => {
    if (disabled) recognition.current?.stop();
  }, [disabled]);
  return (
    <div className="voice-controls">
      <Button
        type="button"
        variant={listening ? "default" : "ghost"}
        size="sm"
        disabled={disabled || !available}
        aria-pressed={listening}
        title={
          available
            ? "El navegador puede procesar la voz mediante un servicio en línea."
            : "Dictado no disponible en este navegador; prueba Chrome o Edge."
        }
        onClick={() => {
          if (listening) {
            recognition.current?.stop();
            return;
          }
          setStatus("");
          try {
            recognition.current?.start();
            setListening(true);
          } catch {
            setStatus("El micrófono sigue ocupado. Vuelve a intentarlo.");
          }
        }}
      >
        {listening ? <MicOff size={16} /> : <Mic size={16} />}
        {listening ? "Detener dictado" : "Dictar"}
      </Button>
      <span className="voice-status muted" role="status" aria-live="polite">
        {interim ||
          status ||
          (listening
            ? "Escuchando… Revisa el texto antes de enviarlo."
            : !available
              ? "Voz no disponible en este navegador"
              : "")}
      </span>
    </div>
  );
}

export function ReadAloud({ text }: { text: string }) {
  const [speaking, setSpeaking] = useState(false);
  const available = useSyncExternalStore(
    subscribeCapabilities,
    speechSynthesisAvailable,
    noCapability,
  );
  const [error, setError] = useState("");
  const ownUtterance = useRef<SpeechSynthesisUtterance | null>(null);
  useEffect(() => {
    return () => {
      if (ownUtterance.current) window.speechSynthesis?.cancel();
    };
  }, []);
  if (!available || !text) return null;
  return (
    <div className="read-aloud">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-label={speaking ? "Detener lectura" : "Leer respuesta en voz alta"}
        onClick={() => {
          window.speechSynthesis.cancel();
          if (speaking) {
            setSpeaking(false);
            ownUtterance.current = null;
            return;
          }
          setError("");
          const utterance = new SpeechSynthesisUtterance(
            text
              .replace(/```[\s\S]*?```/g, " Bloque de código. ")
              .replace(/[*#`]/g, ""),
          );
          utterance.lang = "es-ES";
          utterance.onend = () => {
            setSpeaking(false);
            ownUtterance.current = null;
          };
          utterance.onerror = (event) => {
            setSpeaking(false);
            ownUtterance.current = null;
            if (event.error !== "interrupted" && event.error !== "canceled")
              setError("No se pudo reproducir la voz.");
          };
          ownUtterance.current = utterance;
          setSpeaking(true);
          window.speechSynthesis.speak(utterance);
        }}
      >
        {speaking ? <Square size={14} /> : <Volume2 size={14} />}
        {speaking ? "Detener" : "Escuchar"}
      </Button>
      {error && (
        <span role="status" className="error">
          {error}
        </span>
      )}
    </div>
  );
}
