import { useEffect, useRef, useState } from "react";
import { usePushToTalk, useSpeechInput, type SpeechInput } from "../voice";

export type VoiceChannel = "log" | "dispatch";

/**
 * One speech recognizer, two channels. Each mic button sets the channel when it starts a session,
 * and the final transcript of that session goes to that channel's handler only. Clinical speech
 * never reaches the dispatch parser: a transcript with no channel is dropped, never sent.
 * A button cannot start (or stop) a session while the other channel is listening.
 */
export function useVoiceChannels(h: { onLog: (text: string) => void; onDispatch: (text: string) => void }) {
  const handlers = useRef(h);
  useEffect(() => {
    handlers.current = h;
  });

  const channelRef = useRef<VoiceChannel | null>(null); // the channel of the latest session
  const busyRef = useRef(false); // a session was started and has not ended yet (sync, unlike `listening`)
  const [channel, setChannel] = useState<VoiceChannel | null>(null);

  const speech = useSpeechInput({
    onFinal: (text) => {
      const c = channelRef.current;
      if (c === "log") handlers.current.onLog(text);
      else if (c === "dispatch") handlers.current.onDispatch(text);
    },
  });

  // The session ended (or failed to start): another one may start.
  useEffect(() => {
    if (!speech.listening) busyRef.current = false;
  }, [speech.listening, speech.error]);

  const start = (c: VoiceChannel) => {
    if (speech.listening || busyRef.current) return;
    channelRef.current = c;
    busyRef.current = true;
    setChannel(c);
    speech.start();
  };
  const stop = (c: VoiceChannel) => {
    if (channelRef.current === c) speech.stop();
  };
  const toggle = (c: VoiceChannel) => {
    if (speech.listening) stop(c);
    else start(c);
  };

  const listeningOn = (c: VoiceChannel) => speech.listening && channel === c;
  const logMic = usePushToTalk({ listening: listeningOn("log"), start: () => start("log"), stop: () => stop("log") });
  const dispatchMic = usePushToTalk({
    listening: listeningOn("dispatch"),
    start: () => start("dispatch"),
    stop: () => stop("dispatch"),
  });

  return {
    speech: speech as SpeechInput,
    channel: speech.listening ? channel : null,
    lastChannel: channel, // the channel of the latest session, listening or not (where to show its error)
    logMic,
    dispatchMic,
    toggle,
  };
}
