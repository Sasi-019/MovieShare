import { useState } from "react";
import { requestMovieAccess } from "../services/api";

export default function MovieCard({
  movie,
  currentUser,
  onDownload,
  downloading,
}) {
  const [requesting, setRequesting] = useState(false);
  const [requestMessage, setRequestMessage] = useState("");
  const [requestError, setRequestError] = useState("");

  const isOwner =
    Number(currentUser?.id) === Number(movie.owner_id);

  const isAdmin = currentUser?.role === "admin";

  const canDownload = isAdmin || isOwner;

  const canRequestAccess = !isAdmin && !isOwner;

  const fileSize =
    movie.file_size != null
      ? `${(movie.file_size / (1024 * 1024)).toFixed(2)} MB`
      : "Unknown size";

  const uploadedDate = movie.created_at
    ? new Date(movie.created_at).toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "Unknown date";

  const uploaderName = movie.uploader?.name || "Unknown user";
  const uploaderEmail = movie.uploader?.email || "Email unavailable";

  async function handleRequestAccess() {
    setRequesting(true);
    setRequestMessage("");
    setRequestError("");

    try {
      const result = await requestMovieAccess(movie.id);

      setRequestMessage(
        result.message || "Access request sent successfully."
      );
    } catch (error) {
      const detail = error.response?.data?.detail;

      setRequestError(
        typeof detail === "string"
          ? detail
          : "Could not request access. Please try again."
      );
    } finally {
      setRequesting(false);
    }
  }

  return (
    <article className="flex h-full flex-col rounded-2xl border border-slate-800 bg-slate-900 p-5 transition hover:border-indigo-500/50">
      {/* Movie header */}
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-indigo-500/10 text-2xl">
          🎬
        </div>

        <span className="max-w-[60%] break-words rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400">
          {movie.content_type || "Video"}
        </span>
      </div>

      {/* Movie title */}
      <h3 className="break-words text-lg font-semibold text-white">
        {movie.title}
      </h3>

      {/* Movie description */}
      <p className="mt-2 flex-1 break-words text-sm leading-6 text-slate-400">
        {movie.description || "No description provided."}
      </p>

      {/* Uploader details */}
      <div className="mt-5 rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4">
        <div className="mb-3 flex items-center gap-2">
          <span className="text-lg" aria-hidden="true">
            👤
          </span>

          <h4 className="text-sm font-semibold text-indigo-300">
            Uploaded by
          </h4>
        </div>

        <p className="break-words text-sm font-medium text-white">
          {uploaderName}
        </p>

        <p className="mt-1 break-all text-xs text-slate-400">
          {uploaderEmail}
        </p>

        <p className="mt-3 text-xs text-slate-500">
          User ID: {movie.uploader?.id ?? movie.owner_id}
        </p>
      </div>

      {/* File information */}
      <div className="mt-4 space-y-3 border-t border-slate-800 pt-4">
        <div>
          <p className="text-xs font-medium text-slate-400">
            Original filename
          </p>

          <p className="mt-1 break-all text-sm text-slate-300">
            {movie.original_filename || "Unknown file"}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-xs font-medium text-slate-400">
              File size
            </p>

            <p className="mt-1 text-sm text-slate-300">
              {fileSize}
            </p>
          </div>

          <div>
            <p className="text-xs font-medium text-slate-400">
              Format
            </p>

            <p className="mt-1 break-words text-sm text-slate-300">
              {movie.content_type || "Unknown"}
            </p>
          </div>
        </div>

        {/* Upload date and time */}
        <div>
          <p className="text-xs font-medium text-slate-400">
            Uploaded on
          </p>

          <p className="mt-1 text-sm text-slate-300">
            {uploadedDate}
          </p>
        </div>
      </div>

      {/* Download or access request */}
      {canDownload ? (
        <button
          type="button"
          onClick={() => onDownload(movie.id)}
          disabled={downloading}
          className="mt-5 w-full rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {downloading ? "Preparing download..." : "Download movie"}
        </button>
      ) : canRequestAccess ? (
        <div className="mt-5">
          <button
            type="button"
            onClick={handleRequestAccess}
            disabled={requesting}
            className="w-full rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {requesting ? "Sending request..." : "Request Access"}
          </button>

          {requestMessage && (
            <p role="status" className="mt-3 text-sm text-emerald-400">
              {requestMessage}
            </p>
          )}

          {requestError && (
            <p role="alert" className="mt-3 text-sm text-red-400">
              {requestError}
            </p>
          )}
        </div>
      ) : null}
    </article>
  );
}