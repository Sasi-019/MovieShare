import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://127.0.0.1:8000",
  headers: {
    Accept: "application/json",
  },
});

// Attach the login token to authenticated requests.
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("movieshare_token");

    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// Register a new user.
export async function registerUser({ name, email, password }) {
  const response = await api.post("/auth/register", {
    name,
    email,
    password,
  });

  return response.data;
}

// Log in an existing user.
export async function loginUser({ email, password }) {
  const response = await api.post("/auth/login", {
    email,
    password,
  });

  const { access_token, user } = response.data;

  localStorage.setItem("movieshare_token", access_token);

  return user;
}

// Get the currently authenticated user.
export async function getCurrentUser() {
  const response = await api.get("/auth/me");
  return response.data;
}

// Log out.
export function logoutUser() {
  localStorage.removeItem("movieshare_token");
}

// Retrieve movies.
export async function getMovies() {
  const response = await api.get("/movies/");
  return response.data;
}

// Search movies by title or description.
export async function searchMovies(query) {
  const response = await api.get("/movies/search", {
    params: {
      q: query,
    },
  });

  return response.data;
}

// Upload a movie.
export async function uploadMovie({ title, description, file }) {
  const formData = new FormData();

  formData.append("title", title);
  formData.append("description", description || "");
  formData.append("file", file);

  const response = await api.post("/movies/upload", formData);

  return response.data;
}

// Request a temporary download URL.
export async function getMovieDownloadUrl(movieId) {
  const response = await api.get(`/movies/${movieId}/download`);
  return response.data;
}

// Retrieve administrator statistics.
export async function getAdminDashboard() {
  const response = await api.get("/admin/dashboard");
  return response.data;
}

// Retrieve all registered users for the administrator.
export async function getAdminUsers() {
  const response = await api.get("/admin/users");
  return response.data;
}

// Block a regular user.
export async function blockUser(userId) {
  const response = await api.patch(`/admin/users/${userId}/block`);
  return response.data;
}

// Unblock a regular user.
export async function unblockUser(userId) {
  const response = await api.patch(`/admin/users/${userId}/unblock`);
  return response.data;
}

// Request access to another user's movie.
export async function requestMovieAccess(movieId) {
  const response = await api.post(
    `/sharing/movies/${movieId}/request`
  );

  return response.data;
}

// Get notifications for the logged-in user.
export async function getSharingNotifications() {
  const response = await api.get("/sharing/notifications");
  return response.data;
}

// Mark a notification as read.
export async function markSharingNotificationRead(notificationId) {
  const response = await api.patch(
    `/sharing/notifications/${notificationId}/read`
  );
  return response.data;
}

// Accept or reject a movie access request.
export async function decideSharingRequest(requestId, decision) {
  const response = await api.patch(
    `/sharing/requests/${requestId}/decision`,
    null,
    {
      params: { decision },
    }
  );
  return response.data;
}

// // Generate a QR image on the owner's device.
// export async function getSharingRequestQR(requestId) {
//   const response = await api.get(
//     `/sharing/requests/${requestId}/qr`,
//     {
//       responseType: "blob",
//     }
//   );

//   return URL.createObjectURL(response.data);
// }

// // Retrieve the owner's generated QR image on the requester's device.
// export async function getRequesterSharingQR(requestId) {
//   const response = await api.get(
//     `/sharing/requests/${requestId}/qr-for-requester`,
//     {
//       responseType: "blob",
//     }
//   );

//   return URL.createObjectURL(response.data);
// }

// // Redeem a QR token and grant temporary movie access.
// export async function validateSharingQR(token) {
//   const response = await api.post(
//     "/sharing/qr/validate",
//     null,
//     {
//       params: { token },
//     }
//   );

//   return response.data;
// }

// // Release a QR image's browser object URL when it is no longer needed.
// export function revokeSharingQRImage(imageUrl) {
//   if (imageUrl && imageUrl.startsWith("blob:")) {
//     URL.revokeObjectURL(imageUrl);
//   }
// }

// export default api;
// Generate a QR image on the movie owner's dashboard.
export async function getSharingRequestQR(requestId) {
  const response = await api.get(
    `/sharing/requests/${requestId}/qr`,
    {
      responseType: "blob",
    }
  );

  return URL.createObjectURL(response.data);
}

// Retrieve the owner's QR image on the requester's dashboard.
export async function getRequesterSharingQR(requestId) {
  const response = await api.get(
    `/sharing/requests/${requestId}/qr-for-requester`,
    {
      responseType: "blob",
    }
  );

  return URL.createObjectURL(response.data);
}

// Redeem the active QR token and grant temporary movie access.
export async function redeemSharingRequestQR(requestId) {
  const response = await api.post(
    `/sharing/requests/${requestId}/redeem`
  );

  return response.data;
}

// Release an image URL when it is no longer needed.
export function revokeSharingQRImage(imageUrl) {
  if (imageUrl && imageUrl.startsWith("blob:")) {
    URL.revokeObjectURL(imageUrl);
  }
}

