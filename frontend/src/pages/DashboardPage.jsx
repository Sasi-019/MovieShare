import { useCallback, useEffect, useRef, useState } from "react";

import StatCard from "../components/StatCard";
import MovieCard from "../components/MovieCard";
import UploadForm from "../components/UploadForm";
import AdminDashboard from "./AdminDashboard";
import ManageUsers from "../components/ManageUsers";

import {
  getSharingRequestQR,
  getRequesterSharingQR,
  redeemSharingRequestQR,
  revokeSharingQRImage,
} from "../services/api";

export default function DashboardPage({
  user,
  movies = [],
  adminStats,
  loadingMovies,
  uploading,
  downloadingMovieId,
  onUpload,
  onDownload,
  onRefresh,
  message,
  error,

  // Movie search props
  searchQuery,
  setSearchQuery,
  searchResults = [],
  searchLoading,
  searchError,
  hasSearched,
  onSearch,
  onClearSearch,

  // Movie-sharing notification props
  sharingNotifications = [],
  loadingSharingNotifications = false,
  sharingActionId = null,
  onSharingDecision,
  onRefreshNotifications,
}) {
  const isAdmin = user?.role === "admin";

  // Owner-side QR state
  const [qrRequestId, setQrRequestId] = useState(null);
  const [qrImageUrl, setQrImageUrl] = useState("");
  const [qrLoading, setQrLoading] = useState(false);

  // Requester-side QR state
  const [requesterQRs, setRequesterQRs] = useState({});
  const [redeemingRequestId, setRedeemingRequestId] = useState(null);
  const [qrMessage, setQrMessage] = useState("");
  const [qrError, setQrError] = useState("");

  const ownerImageRef = useRef("");
  const requesterImagesRef = useRef({});
  const redeemedRequestsRef = useRef(new Set());

  const sameId = (first, second) =>
    first != null &&
    second != null &&
    String(first) === String(second);

  // Statistics
  const totalMovies = movies.length;

  const totalStorageBytes = movies.reduce(
    (total, movie) => total + (Number(movie.file_size) || 0),
    0
  );

  const formatStorage = (bytes) => {
    if (!bytes) return "0 MB";

    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(2)} KB`;
    }

    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  const displayedMovies = hasSearched ? searchResults : movies;

  const getDecision = (notification) =>
    String(notification?.decision || "pending").toLowerCase();

  // The backend may use sharing_request_accepted for requester notifications.
  const isSharingRequestNotification = (notification) =>
    String(notification?.type || "").startsWith("sharing_request") &&
    notification?.sharing_request_id != null;

  // Requests accepted for the currently logged-in owner or requester.
  const acceptedSharingNotifications = sharingNotifications.filter(
    (notification) => {
      if (
        !isSharingRequestNotification(notification) ||
        getDecision(notification) !== "accepted"
      ) {
        return false;
      }

      return (
        sameId(notification.owner_id, user?.id) ||
        sameId(notification.requester_id, user?.id)
      );
    }
  );

  const refreshDashboard = useCallback(async () => {
    try {
      if (typeof onRefresh === "function") {
        await onRefresh();
      }
    } catch (refreshError) {
      console.error("Unable to refresh movies:", refreshError);
    }

    try {
      if (typeof onRefreshNotifications === "function") {
        await onRefreshNotifications();
      }
    } catch (refreshError) {
      console.error("Unable to refresh sharing notifications:", refreshError);
    }
  }, [onRefresh, onRefreshNotifications]);

  // Owner generates a QR code for an accepted sharing request.
  const handleGenerateQR = async (requestId) => {
    if (qrLoading) return;

    setQrLoading(true);
    setQrError("");
    setQrMessage("");

    try {
      const imageUrl = await getSharingRequestQR(requestId);

      if (ownerImageRef.current) {
        revokeSharingQRImage(ownerImageRef.current);
      }

      ownerImageRef.current = imageUrl;

      setQrImageUrl(imageUrl);
      setQrRequestId(requestId);

      setQrMessage(
        "QR generated successfully. It is now available on the requester's dashboard."
      );

      // Refresh local notifications after generation.
      if (typeof onRefreshNotifications === "function") {
        await onRefreshNotifications();
      }
    } catch (err) {
      setQrError(
        err.response?.data?.detail ||
          "Unable to generate the QR code. Confirm that you own the movie and the request has been accepted."
      );
    } finally {
      setQrLoading(false);
    }
  };

  const handleCloseQR = () => {
    if (ownerImageRef.current) {
      revokeSharingQRImage(ownerImageRef.current);
      ownerImageRef.current = "";
    }

    setQrImageUrl("");
    setQrRequestId(null);
  };

  // Requester redeems the active QR without needing a camera.
  const handleRedeemQR = async (requestId) => {
    if (redeemingRequestId !== null) return;

    setRedeemingRequestId(requestId);
    setQrError("");
    setQrMessage("");

    try {
      const result = await redeemSharingRequestQR(requestId);

      redeemedRequestsRef.current.add(String(requestId));

      // Remove the displayed QR after successful redemption.
      setRequesterQRs((previous) => {
        const imageUrl = previous[requestId];

        if (imageUrl) {
          revokeSharingQRImage(imageUrl);
        }

        const next = { ...previous };
        delete next[requestId];
        return next;
      });

      setQrMessage(
        result?.message ||
          "Access granted! You can now download the movie while your access remains valid."
      );

      await refreshDashboard();
    } catch (err) {
      setQrError(
        err.response?.data?.detail ||
          "Unable to obtain movie access. The QR may have expired or already been used. Ask the owner to generate a new QR."
      );
    } finally {
      setRedeemingRequestId(null);
    }
  };

  // Poll notifications so the requester notices newly generated QR codes.
  useEffect(() => {
    if (typeof onRefreshNotifications !== "function") {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      onRefreshNotifications();
    }, 4000);

    return () => window.clearInterval(intervalId);
  }, [onRefreshNotifications]);

  // Load the QR image for accepted requests where this user is the requester.
  // The endpoint may return an error before the owner has generated a QR.
  useEffect(() => {
    let cancelled = false;

    const loadRequesterQRs = async () => {
      const requesterRequests = acceptedSharingNotifications.filter(
        (notification) =>
          sameId(notification.requester_id, user?.id) &&
          !redeemedRequestsRef.current.has(
            String(notification.sharing_request_id)
          )
      );

      for (const notification of requesterRequests) {
        if (cancelled) return;

        const requestId = notification.sharing_request_id;
        const key = String(requestId);

        // Don't download the same QR image repeatedly.
        if (requesterImagesRef.current[key]) continue;

        try {
          const imageUrl = await getRequesterSharingQR(requestId);

          if (cancelled) {
            revokeSharingQRImage(imageUrl);
            return;
          }

          requesterImagesRef.current[key] = imageUrl;

          setRequesterQRs((previous) => ({
            ...previous,
            [key]: imageUrl,
          }));
        } catch {
          // No active QR yet, or the QR expired.
          // Keep checking on the next notifications update.
        }
      }
    };

    loadRequesterQRs();

    return () => {
      cancelled = true;
    };
  }, [acceptedSharingNotifications, user?.id]);

  // Clean up QR image object URLs when the component unmounts.
  useEffect(() => {
    return () => {
      if (ownerImageRef.current) {
        revokeSharingQRImage(ownerImageRef.current);
        ownerImageRef.current = "";
      }

      Object.values(requesterImagesRef.current).forEach((imageUrl) => {
        revokeSharingQRImage(imageUrl);
      });

      requesterImagesRef.current = {};
    };
  }, []);

  return (
    <main className="min-h-screen bg-slate-950 text-white">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        {/* Dashboard heading */}
        <section className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-indigo-400">
              {isAdmin ? "ADMINISTRATOR DASHBOARD" : "YOUR WORKSPACE"}
            </p>

            <h1 className="mt-2 text-3xl font-bold tracking-tight">
              Welcome, {user?.name || "User"}!
            </h1>

            <p className="mt-2 text-sm text-slate-400">
              {isAdmin
                ? "Monitor the MovieShare platform and manage your movie library."
                : "Upload, organize, search, and access your movie collection."}
            </p>
          </div>

          <button
            type="button"
            onClick={onRefresh}
            disabled={loadingMovies}
            className="rounded-xl border border-slate-700 px-4 py-3 text-sm font-medium text-slate-300 transition hover:border-indigo-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loadingMovies ? "Refreshing..." : "↻ Refresh"}
          </button>
        </section>

        {/* Success message */}
        {message && (
          <div
            role="status"
            className="mb-6 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300"
          >
            {message}
          </div>
        )}

        {/* General error message */}
        {error && (
          <div
            role="alert"
            className="mb-6 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300"
          >
            {error}
          </div>
        )}

        {/* Sharing notifications */}
        <section className="mb-8 rounded-2xl border border-slate-800 bg-slate-900/70 p-5 sm:p-6">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium uppercase tracking-wider text-indigo-400">
                Secure movie sharing
              </p>

              <h2 className="mt-2 text-2xl font-bold">
                Movie Access Requests
              </h2>

              <p className="mt-2 text-sm text-slate-400">
                Review notifications and manage requests to access your movies.
              </p>
            </div>

            <button
              type="button"
              onClick={onRefreshNotifications}
              disabled={loadingSharingNotifications}
              className="rounded-xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 transition hover:border-indigo-500 hover:text-white disabled:opacity-50"
            >
              {loadingSharingNotifications
                ? "Refreshing..."
                : "↻ Refresh requests"}
            </button>
          </div>

          {loadingSharingNotifications &&
          sharingNotifications.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-400">
              Loading notifications...
            </p>
          ) : sharingNotifications.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-700 px-4 py-8 text-center">
              <p className="text-lg">🔔</p>
              <p className="mt-2 font-medium text-slate-200">
                No notifications yet
              </p>
              <p className="mt-1 text-sm text-slate-400">
                New movie-sharing activity will appear here.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {sharingNotifications.map((notification) => {
                const isSharingRequest =
                  isSharingRequestNotification(notification);

                const decision = getDecision(notification);
                const isPending = decision === "pending";
                const isAccepted = decision === "accepted";
                const isRejected = decision === "rejected";

                const actionInProgress = sameId(
                  sharingActionId,
                  notification.sharing_request_id
                );

                return (
                  <article
                    key={notification.id}
                    className={`rounded-xl border p-4 ${
                      notification.is_read
                        ? "border-slate-800 bg-slate-950/60"
                        : "border-indigo-500/40 bg-indigo-500/5"
                    }`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold uppercase tracking-wide text-indigo-300">
                            {String(
                              notification.type || "notification"
                            ).replaceAll("_", " ")}
                          </span>

                          {!notification.is_read && (
                            <span className="rounded-full bg-indigo-500/15 px-2 py-1 text-xs text-indigo-300">
                              New
                            </span>
                          )}
                        </div>

                        <p className="mt-2 text-sm leading-6 text-slate-200">
                          {notification.message}
                        </p>

                        <p className="mt-2 text-xs text-slate-500">
                          {notification.created_at
                            ? new Date(
                                notification.created_at
                              ).toLocaleString()
                            : "Date unavailable"}
                        </p>
                      </div>

                      {isSharingRequest && (
                        <span
                          className={`rounded-full px-3 py-1 text-xs font-semibold ${
                            isPending
                              ? "bg-amber-500/15 text-amber-300"
                              : isAccepted
                                ? "bg-emerald-500/15 text-emerald-300"
                                : isRejected
                                  ? "bg-red-500/15 text-red-300"
                                  : "bg-slate-700 text-slate-200"
                          }`}
                        >
                          {isPending
                            ? "Pending"
                            : isAccepted
                              ? "Accepted"
                              : isRejected
                                ? "Rejected"
                                : decision}
                        </span>
                      )}
                    </div>

                    {isSharingRequest && isPending && (
                      <div className="mt-4 flex flex-wrap gap-3">
                        <button
                          type="button"
                          disabled={
                            actionInProgress ||
                            typeof onSharingDecision !== "function"
                          }
                          onClick={() =>
                            onSharingDecision(
                              notification.sharing_request_id,
                              "accepted"
                            )
                          }
                          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {actionInProgress ? "Processing..." : "Accept"}
                        </button>

                        <button
                          type="button"
                          disabled={
                            actionInProgress ||
                            typeof onSharingDecision !== "function"
                          }
                          onClick={() =>
                            onSharingDecision(
                              notification.sharing_request_id,
                              "rejected"
                            )
                          }
                          className="rounded-lg bg-red-600/90 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {actionInProgress ? "Processing..." : "Reject"}
                        </button>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>

        {/* Automatic QR sharing */}
        <section className="mb-8 rounded-2xl border border-slate-800 bg-slate-900/70 p-5 sm:p-6">
          <p className="text-sm font-semibold uppercase tracking-wider text-indigo-400">
            Secure movie sharing
          </p>

          <h2 className="mt-2 text-2xl font-bold">QR Code Access</h2>

          <p className="mt-2 text-sm text-slate-400">
            Owners generate a temporary QR code. The accepted requester sees
            it automatically and can redeem it to obtain temporary download access.
          </p>

          {acceptedSharingNotifications.length > 0 ? (
            <div className="mt-4 space-y-4">
              {acceptedSharingNotifications.map((notification) => {
                const requestId = notification.sharing_request_id;
                const isOwner = sameId(notification.owner_id, user?.id);
                const isRequester = sameId(
                  notification.requester_id,
                  user?.id
                );

                if (!isOwner && !isRequester) return null;

                const requesterQR = requesterQRs[String(requestId)];

                return (
                  <div
                    key={requestId}
                    className="rounded-xl border border-slate-700 p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="font-medium text-slate-200">
                          {notification.movie_title ||
                            notification.message ||
                            `Sharing request #${requestId}`}
                        </p>

                        <span className="mt-1 inline-block text-xs font-medium text-emerald-400">
                          Request accepted
                        </span>

                        <p className="mt-1 text-xs text-slate-400">
                          {isOwner
                            ? "You own this movie. Generate a QR code to make it available to the requester."
                            : requesterQR
                              ? "The owner's QR code is ready. Select Get Movie Access to redeem it."
                              : "Waiting for the owner to generate a QR code. This section checks automatically."}
                        </p>
                      </div>

                      {isOwner && (
                        <button
                          type="button"
                          disabled={qrLoading}
                          onClick={() => handleGenerateQR(requestId)}
                          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {qrLoading && sameId(qrRequestId, requestId)
                            ? "Generating..."
                            : "Generate QR"}
                        </button>
                      )}
                    </div>

                    {/* Requester's automatically retrieved QR */}
                    {isRequester && requesterQR && (
                      <div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 text-center">
                        <h3 className="font-semibold text-white">
                          QR code received
                        </h3>

                        <img
                          src={requesterQR}
                          alt={`Secure access QR for sharing request ${requestId}`}
                          className="mx-auto mt-4 h-64 w-64 rounded-lg bg-white object-contain p-2"
                        />

                        <p className="mt-3 text-sm text-slate-400">
                          This QR expires after five minutes and can be
                          redeemed once.
                        </p>

                        <button
                          type="button"
                          onClick={() => handleRedeemQR(requestId)}
                          disabled={redeemingRequestId !== null}
                          className="mt-4 rounded-lg bg-emerald-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {sameId(redeemingRequestId, requestId)
                            ? "Granting access..."
                            : "Get Movie Access"}
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-slate-700 p-5 text-center">
              <p className="font-medium text-slate-200">
                No accepted requests available
              </p>

              <p className="mt-1 text-sm text-slate-400">
                Accepted requests involving your account will appear here.
              </p>
            </div>
          )}

          {/* Owner's generated QR */}
          {qrImageUrl && (
            <div className="mt-5 rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-5 text-center">
              <h3 className="font-semibold text-white">
                QR generated — Request #{qrRequestId}
              </h3>

              <img
                src={qrImageUrl}
                alt="Secure movie access QR code"
                className="mx-auto mt-4 h-64 w-64 rounded-lg bg-white object-contain p-2"
              />

              <p className="mt-3 text-sm text-slate-400">
                QR generated successfully. The requester can retrieve it
                from their dashboard. It expires after five minutes and
                can be redeemed once.
              </p>

              <button
                type="button"
                onClick={handleCloseQR}
                className="mt-3 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 transition hover:bg-slate-800"
              >
                Close QR
              </button>
            </div>
          )}

          {qrMessage && (
            <div
              role="status"
              className="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300"
            >
              {qrMessage}
            </div>
          )}

          {qrError && (
            <div
              role="alert"
              className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
            >
              {qrError}
            </div>
          )}
        </section>

        {/* Administrator dashboard */}
        {isAdmin && (
          <>
            <AdminDashboard stats={adminStats} />
            <ManageUsers />
          </>
        )}

        {/* Personal library statistics */}
        <section className="mb-8">
          <div className="mb-4">
            <h2 className="text-xl font-bold">
              {isAdmin ? "Movie library" : "Your library"}
            </h2>

            <p className="mt-1 text-sm text-slate-400">
              {isAdmin
                ? "Browse the movies available in the library."
                : "A quick overview of the movies currently listed in your library."}
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <StatCard
              label="Movies listed"
              value={totalMovies}
              detail="Movies returned by the movie API"
              icon="🎞️"
            />

            <StatCard
              label="Listed file size"
              value={formatStorage(totalStorageBytes)}
              detail="Combined size of the listed movie files"
              icon="💾"
            />
          </div>
        </section>

        {/* Movie upload form */}
        <section className="mb-10">
          <UploadForm onUpload={onUpload} uploading={uploading} />
        </section>

        {/* Movie search */}
        <section className="mb-10 rounded-2xl border border-slate-800 bg-slate-900/70 p-5 sm:p-6">
          <div className="mb-5">
            <p className="text-sm font-medium uppercase tracking-wider text-indigo-400">
              Discover movies
            </p>

            <h2 className="mt-2 text-2xl font-bold">
              Search the movie library
            </h2>

            <p className="mt-2 text-sm text-slate-400">
              Search by movie title or keywords in its description.
            </p>
          </div>

          <form
            onSubmit={(event) => {
              event.preventDefault();
              onSearch?.();
            }}
            className="flex flex-col gap-3 sm:flex-row"
          >
            <div className="relative flex-1">
              <label htmlFor="movie-search" className="sr-only">
                Search movies
              </label>

              <input
                id="movie-search"
                type="search"
                value={searchQuery ?? ""}
                onChange={(event) => setSearchQuery?.(event.target.value)}
                placeholder="Enter a movie title or keyword..."
                maxLength={200}
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-500 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
              />
            </div>

            <button
              type="submit"
              disabled={searchLoading}
              className="rounded-xl bg-indigo-600 px-6 py-3 font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {searchLoading ? "Searching..." : "🔍 Search"}
            </button>

            {hasSearched && (
              <button
                type="button"
                onClick={onClearSearch}
                disabled={searchLoading}
                className="rounded-xl border border-slate-700 px-5 py-3 font-medium text-slate-300 transition hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                Clear
              </button>
            )}
          </form>

          {searchError && (
            <div
              role="alert"
              className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300"
            >
              {searchError}
            </div>
          )}

          {searchLoading && (
            <div
              role="status"
              className="mt-5 flex items-center gap-3 text-sm text-slate-300"
            >
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-600 border-t-indigo-400" />
              Searching the movie library...
            </div>
          )}

          {hasSearched && !searchLoading && !searchError && (
            <p className="mt-4 text-sm text-slate-400">
              {searchResults.length === 0
                ? "No matching movies were found."
                : `Found ${searchResults.length} matching ${
                    searchResults.length === 1 ? "movie" : "movies"
                  }.`}
            </p>
          )}
        </section>

        {/* Movie collection or search results */}
        <section>
          <div className="mb-5">
            <h2 className="text-2xl font-bold">
              {hasSearched ? "Search results" : "Movie collection"}
            </h2>

            <p className="mt-2 text-sm text-slate-400">
              {hasSearched
                ? "Movies matching your search, including their uploader information."
                : "Select a movie to download it if your account has permission."}
            </p>
          </div>

          {!hasSearched && loadingMovies && movies.length === 0 ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-900 px-6 py-12 text-center">
              <p className="text-slate-300">
                Loading your movie collection...
              </p>
            </div>
          ) : searchLoading ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-900 px-6 py-12 text-center">
              <p className="text-slate-300">Loading search results...</p>
            </div>
          ) : searchError && hasSearched ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-900 px-6 py-12 text-center">
              <p className="text-slate-300">
                Search results could not be loaded.
              </p>

              <p className="mt-2 text-sm text-slate-500">
                Check the error message above and try again.
              </p>
            </div>
          ) : displayedMovies.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/50 px-6 py-12 text-center">
              <div className="text-4xl">
                {hasSearched ? "🔎" : "🎬"}
              </div>

              <h3 className="mt-4 text-lg font-semibold">
                {hasSearched ? "No matching movies" : "No movies found"}
              </h3>

              <p className="mt-2 text-sm text-slate-400">
                {hasSearched
                  ? "Try another title or keyword. You can also clear your search to return to the complete collection."
                  : "Upload your first video to get started."}
              </p>
            </div>
          ) : (
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {displayedMovies.map((movie) => (
                <MovieCard
                  key={movie.id}
                  movie={movie}
                  currentUser={user}
                  onDownload={onDownload}
                  downloading={
                    Number(downloadingMovieId) === Number(movie.id)
                  }
                />
              ))}
            </div>
          )}
        </section>

        {/* Footer */}
        <footer className="mt-12 border-t border-slate-800 pt-6 text-center text-xs text-slate-500">
          MovieShare · Secure cloud-based movie sharing
        </footer>
      </div>
    </main>
  );
}