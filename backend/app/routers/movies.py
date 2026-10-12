import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.database import get_db

from app.routers.routes import get_current_user

from app.models import (
    Movie,
    MovieAccessGrant,
    SharingRequest,
    User,
)
# Load environment variables from backend/.env
load_dotenv()

router = APIRouter(prefix="/movies", tags=["Movies"])


# Backblaze B2 configuration
B2_KEY_ID = os.getenv("B2_KEY_ID")
B2_APPLICATION_KEY = os.getenv("B2_APPLICATION_KEY")
B2_BUCKET_NAME = os.getenv("B2_BUCKET_NAME")
B2_ENDPOINT_URL = os.getenv("B2_ENDPOINT_URL")

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

DOWNLOAD_LINK_EXPIRY_SECONDS = 600  # 10 minutes

ALLOWED_VIDEO_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
}


def get_s3_client():
    """Create a Backblaze B2 S3-compatible client."""

    if not all(
        [
            B2_KEY_ID,
            B2_APPLICATION_KEY,
            B2_BUCKET_NAME,
            B2_ENDPOINT_URL,
        ]
    ):
        raise HTTPException(
            status_code=500,
            detail="Backblaze storage is not configured.",
        )

    return boto3.client(
        "s3",
        endpoint_url=B2_ENDPOINT_URL,
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APPLICATION_KEY,
        region_name="us-east-005",
    )


def serialize_movie(movie: Movie, uploader: User | None = None):
    """
    Convert a movie database record into a response.

    Includes uploader details but never exposes the private
    Backblaze storage key.
    """

    result = {
        "id": movie.id,
        "title": movie.title,
        "description": movie.description,
        "original_filename": movie.original_filename,
        "content_type": movie.content_type,
        "file_size": movie.file_size,
        "owner_id": movie.owner_id,
        "created_at": movie.created_at,
    }

    # Include uploader information when the user record is available.
    if uploader is not None:
        result["uploader"] = {
            "id": uploader.id,
            "name": uploader.name,
            "email": uploader.email,
        }

    return result


# --------------------------------------------------
# 1. UPLOAD A MOVIE
# --------------------------------------------------

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_movie(
    title: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a video to private B2 storage."""

    title = title.strip()

    if not title or len(title) > 200:
        raise HTTPException(
            status_code=400,
            detail="Title must contain between 1 and 200 characters.",
        )

    original_filename = Path(file.filename or "").name

    if not original_filename:
        raise HTTPException(
            status_code=400,
            detail="A filename is required.",
        )

    content_type = (file.content_type or "").lower()

    if content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported video type. Use MP4, WebM, or QuickTime.",
        )

    try:
        contents = await file.read(MAX_FILE_SIZE + 1)

        if not contents:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty.",
            )

        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="The maximum upload size is 100 MB.",
            )

        extension = Path(original_filename).suffix.lower()
        storage_key = f"movies/{uuid.uuid4().hex}{extension}"

        s3 = get_s3_client()

        try:
            s3.put_object(
                Bucket=B2_BUCKET_NAME,
                Key=storage_key,
                Body=contents,
                ContentType=content_type,
            )
        except ClientError:
            raise HTTPException(
                status_code=502,
                detail="Could not upload the video to cloud storage.",
            )

        movie = Movie(
            title=title,
            description=description.strip() or None,
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            file_size=len(contents),
            owner_id=current_user.id,
        )

        try:
            db.add(movie)
            db.commit()
            db.refresh(movie)

        except Exception:
            db.rollback()

            try:
                s3.delete_object(
                    Bucket=B2_BUCKET_NAME,
                    Key=storage_key,
                )
            except ClientError:
                pass

            raise HTTPException(
                status_code=500,
                detail="Could not save the movie record.",
            )

        return {
            "message": "Movie uploaded successfully.",
            "movie": serialize_movie(
                movie,
                uploader=current_user,
            ),
        }

    finally:
        await file.close()


# --------------------------------------------------
# 2. LIST ALL MOVIES WITH UPLOADER DETAILS
# --------------------------------------------------

@router.get("/")
def list_movies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Every authenticated user can see all uploaded movies
    and their uploader's name and email.

    Download permissions are enforced separately by the
    download endpoint.

    Private storage keys are never returned.
    """

    movies_with_uploaders = (
        db.query(Movie, User)
        .join(User, Movie.owner_id == User.id)
        .order_by(Movie.created_at.desc())
        .all()
    )

    movies = [
        serialize_movie(movie, uploader=uploader)
        for movie, uploader in movies_with_uploaders
    ]

    return {
        "total": len(movies),
        "movies": movies,
    }

# --------------------------------------------------
# 3. SEARCH MOVIES
# --------------------------------------------------

@router.get("/search")
def search_movies(
    q: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Search movies by title or description.

    Returns matching movies with uploader details.
    Private Backblaze storage keys are never returned.
    """

    search_term = q.strip()

    if not search_term:
        raise HTTPException(
            status_code=400,
            detail="Search query cannot be empty.",
        )

    if len(search_term) > 200:
        raise HTTPException(
            status_code=400,
            detail="Search query cannot exceed 200 characters.",
        )

    search_pattern = f"%{search_term}%"

    results = (
        db.query(Movie, User)
        .join(User, Movie.owner_id == User.id)
        .filter(
            Movie.title.ilike(search_pattern)
            | Movie.description.ilike(search_pattern)
        )
        .order_by(Movie.created_at.desc())
        .limit(50)
        .all()
    )

    movies = [
        serialize_movie(movie, uploader=uploader)
        for movie, uploader in results
    ]

    return {
        "query": search_term,
        "total": len(movies),
        "movies": movies,
    }


# --------------------------------------------------
# 3. GET A TEMPORARY DOWNLOAD LINK
# --------------------------------------------------

# --------------------------------------------------
# 4. GET A TEMPORARY DOWNLOAD LINK
# --------------------------------------------------

@router.get("/{movie_id}/download")
def download_movie(
    movie_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a temporary download URL for a movie.

    Access is allowed to:
    1. The movie owner.
    2. An active administrator.
    3. A user with a valid, accepted sharing grant.

    The movie must belong to an active owner.
    Private Backblaze storage keys are never returned.
    """

    # 1. Reject inactive users.
    if not current_user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Your account is inactive.",
        )

    # 2. Find the requested movie.
    movie = (
        db.query(Movie)
        .filter(Movie.id == movie_id)
        .first()
    )

    if movie is None:
        raise HTTPException(
            status_code=404,
            detail="Movie not found.",
        )

    # 3. Confirm that the movie's owner exists and is active.
    owner = (
        db.query(User)
        .filter(User.id == movie.owner_id)
        .first()
    )

    if owner is None or not owner.is_active:
        raise HTTPException(
            status_code=403,
            detail="This movie's owner is inactive.",
        )

    # 4. Preserve owner and administrator access.
    is_owner = movie.owner_id == current_user.id
    is_admin = current_user.role == "admin"

    has_sharing_grant = False

    # 5. If neither owner nor administrator, check sharing access.
    if not is_owner and not is_admin:
        now = datetime.now(timezone.utc)

        grant = (
            db.query(MovieAccessGrant)
            .join(
                SharingRequest,
                MovieAccessGrant.sharing_request_id
                == SharingRequest.id,
            )
            .filter(
                MovieAccessGrant.user_id == current_user.id,
                MovieAccessGrant.movie_id == movie.id,
                MovieAccessGrant.revoked.is_(False),
                MovieAccessGrant.expires_at > now,
                SharingRequest.status == "accepted",
                SharingRequest.requester_id == current_user.id,
                SharingRequest.movie_id == movie.id,
                SharingRequest.owner_id == movie.owner_id,
            )
            .first()
        )

        if grant is None:
            raise HTTPException(
                status_code=403,
                detail=(
                    "You are not allowed to download this movie. "
                    "An active sharing grant is required."
                ),
            )

        has_sharing_grant = True

    # 6. Generate a short-lived URL for the private B2 object.
    s3 = get_s3_client()

    try:
        download_url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": B2_BUCKET_NAME,
                "Key": movie.storage_key,
                "ResponseContentDisposition": (
                    f'attachment; filename="{Path(movie.original_filename).name}"'
                ),
            },
            ExpiresIn=DOWNLOAD_LINK_EXPIRY_SECONDS,
        )

    except ClientError:
        raise HTTPException(
            status_code=502,
            detail="Could not generate the download link.",
        )

    # 7. Return the temporary URL without exposing the storage key.
    return {
        "message": "Download link generated successfully.",
        "movie_id": movie.id,
        "title": movie.title,
        "download_url": download_url,
        "expires_in_seconds": DOWNLOAD_LINK_EXPIRY_SECONDS,
        "access_type": (
            "owner"
            if is_owner
            else "admin"
            if is_admin
            else "shared"
        ),
        "sharing_grant_used": has_sharing_grant,
    }

