


from app.models import (
    Movie,
    MovieAccessGrant,
    Notification,
    SharingQRToken,
    SharingRequest,
    User,
)

import hashlib
import io
import secrets
from datetime import datetime, timedelta, timezone

import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.database import get_db

from app.routers.routes import get_current_user

import os

from cryptography.fernet import Fernet, InvalidToken
# 1. REQUEST ACCESS TO A MOVIE
# --------------------------------------------------

router = APIRouter(prefix="/sharing", tags=["Movie Sharing"])

def get_qr_cipher() -> Fernet:
    """
    Return the Fernet cipher used to encrypt QR tokens.

    QR_ENCRYPTION_KEY must be configured in the backend .env file.
    """
    key = os.getenv("QR_ENCRYPTION_KEY")

    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="QR encryption is not configured.",
        )

    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="QR encryption configuration is invalid.",
        )
@router.post(
    "/movies/{movie_id}/request",
    status_code=status.HTTP_201_CREATED,
)
def request_movie_access(
    movie_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Request access to another user's movie.

    Creates a pending sharing request and notifies
    the movie owner.
    """

    # 1. Check that the movie exists.
    movie = (
        db.query(Movie)
        .filter(Movie.id == movie_id)
        .first()
    )

    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie not found.",
        )

    # 2. Prevent users from requesting their own movies.
    if movie.owner_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot request access to your own movie.",
        )

    # 3. Check that the owner exists and is active.
    owner = (
        db.query(User)
        .filter(User.id == movie.owner_id)
        .first()
    )

    if owner is None or not owner.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This movie's owner is not available.",
        )

    # 4. Prevent duplicate requests.
    existing_request = (
        db.query(SharingRequest)
        .filter(
            SharingRequest.movie_id == movie.id,
            SharingRequest.requester_id == current_user.id,
        )
        .first()
    )

    if existing_request is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You have already requested access to this movie. "
                f"Current status: {existing_request.status}."
            ),
        )

    # 5. Create the sharing request.
    sharing_request = SharingRequest(
        movie_id=movie.id,
        requester_id=current_user.id,
        owner_id=owner.id,
        status="pending",
    )

    try:
        db.add(sharing_request)
        db.flush()

        # 6. Notify the movie owner.
        notification = Notification(
            user_id=owner.id,
            sharing_request_id=sharing_request.id,
            type="sharing_request",
            message=(
                f"{current_user.name} requested access "
                f"to your movie '{movie.title}'."
            ),
            is_read=False,
        )

        db.add(notification)
        db.commit()
        db.refresh(sharing_request)

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the sharing request.",
        )

    return {
        "message": "Movie access request sent successfully.",
        "request": {
            "id": sharing_request.id,
            "movie_id": sharing_request.movie_id,
            "movie_title": movie.title,
            "requester_id": sharing_request.requester_id,
            "owner_id": sharing_request.owner_id,
            "status": sharing_request.status,
            "created_at": sharing_request.created_at,
        },
    }

@router.patch("/requests/{request_id}/decision")
def decide_sharing_request(
    request_id: int,
    decision: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only accept or reject are valid decisions.
    decision = decision.lower().strip()

    if decision not in ["accepted", "rejected"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decision must be 'accepted' or 'rejected'.",
        )

    # Find the sharing request.
    sharing_request = (
        db.query(SharingRequest)
        .filter(SharingRequest.id == request_id)
        .first()
    )

    if sharing_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sharing request not found.",
        )

    # Only the movie owner can decide.
    if sharing_request.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the movie owner can decide this request.",
        )

    # Do not allow a request to be decided more than once.
    if sharing_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This request has already been {sharing_request.status}.",
        )

    # Verify that the requester is still active.
    requester = (
        db.query(User)
        .filter(User.id == sharing_request.requester_id)
        .first()
    )

    if requester is None or not requester.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The requester is no longer active.",
        )

    # Update the request.
    sharing_request.status = decision

    # Create a notification for the requester.
    movie = db.query(Movie).filter(
        Movie.id == sharing_request.movie_id
    ).first()

    movie_title = movie.title if movie else "the movie"

    notification = Notification(
        user_id=requester.id,
        sharing_request_id=sharing_request.id,
        type=f"sharing_request_{decision}",
        message=(
            f"Your request to access '{movie_title}' "
            f"has been {decision}."
        ),
        is_read=False,
    )

    try:
        db.add(notification)
        db.commit()
        db.refresh(sharing_request)

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update the sharing request.",
        )

    return {
        "message": f"Sharing request {decision} successfully.",
        "request": {
            "id": sharing_request.id,
            "movie_id": sharing_request.movie_id,
            "requester_id": sharing_request.requester_id,
            "owner_id": sharing_request.owner_id,
            "status": sharing_request.status,
            "updated_at": sharing_request.updated_at,
        },
    }

@router.get("/notifications")
def get_sharing_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notifications = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )

    results = []

    for notification in notifications:
        item = {
            "id": notification.id,
            "type": notification.type,
            "message": notification.message,
            "sharing_request_id": notification.sharing_request_id,
            "is_read": notification.is_read,
            "created_at": (
                notification.created_at.isoformat()
                if notification.created_at
                else None
            ),
            "decision": None,
            "owner_id": None,
            "requester_id": None,
            "movie_id": None,
            "movie_title": None,
        }

        if notification.sharing_request_id is not None:
            sharing_request = (
                db.query(SharingRequest)
                .filter(
                    SharingRequest.id == notification.sharing_request_id
                )
                .first()
            )

            if sharing_request:
                item["decision"] = sharing_request.status
                item["owner_id"] = sharing_request.owner_id
                item["requester_id"] = sharing_request.requester_id
                item["movie_id"] = sharing_request.movie_id

                movie = (
                    db.query(Movie)
                    .filter(Movie.id == sharing_request.movie_id)
                    .first()
                )

                if movie:
                    item["movie_title"] = movie.title

        results.append(item)

    return {"notifications": results}

@router.patch("/notifications/{notification_id}/read")
def mark_notification_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
        .first()
    )

    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    notification.is_read = True

    try:
        db.commit()
        db.refresh(notification)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not mark notification as read.",
        )

    return {
        "message": "Notification marked as read.",
        "notification": {
            "id": notification.id,
            "is_read": notification.is_read,
        },
    }


# 5. GENERATE A QR CODE FOR AN ACCEPTED SHARING REQUEST
# --------------------------------------------------


# 5. GENERATE A QR CODE FOR AN ACCEPTED SHARING REQUEST
# --------------------------------------------------

@router.get("/requests/{request_id}/qr")
def generate_sharing_qr(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a short-lived QR code for an accepted sharing request.

    Only the movie owner can generate the QR.
    The intended requester can retrieve the same QR separately.
    The raw token is encrypted before being stored.
    """

    sharing_request = (
        db.query(SharingRequest)
        .filter(SharingRequest.id == request_id)
        .with_for_update()
        .first()
    )

    if sharing_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sharing request not found.",
        )

    if sharing_request.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the movie owner can generate this QR code.",
        )

    if sharing_request.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="QR codes are available only for accepted requests.",
        )

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not active.",
        )

    requester = (
        db.query(User)
        .filter(User.id == sharing_request.requester_id)
        .first()
    )

    if requester is None or not requester.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The requester is not active.",
        )

    movie = (
        db.query(Movie)
        .filter(
            Movie.id == sharing_request.movie_id,
            Movie.owner_id == sharing_request.owner_id,
        )
        .first()
    )

    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The shared movie no longer exists.",
        )

    try:
        cipher = get_qr_cipher()

        # Revoke all previous unused tokens for this request.
        db.query(SharingQRToken).filter(
            SharingQRToken.sharing_request_id == sharing_request.id,
            SharingQRToken.used_at.is_(None),
            SharingQRToken.revoked.is_(False),
        ).update(
            {"revoked": True},
            synchronize_session=False,
        )

        # Generate a cryptographically random, one-time token.
        raw_token = secrets.token_urlsafe(32)

        token_hash = hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()

        encrypted_token = cipher.encrypt(
            raw_token.encode("utf-8")
        ).decode("utf-8")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=5)

        qr_token = SharingQRToken(
            sharing_request_id=sharing_request.id,
            token_hash=token_hash,
            encrypted_token=encrypted_token,
            expires_at=expires_at,
            used_at=None,
            revoked=False,
        )

        db.add(qr_token)
        db.commit()

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate the sharing QR code.",
        )

    # Generate the image in memory.
    qr_image = qrcode.make(raw_token)

    image_buffer = io.BytesIO()
    qr_image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    return StreamingResponse(
        image_buffer,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/requests/{request_id}/qr-for-requester")
def get_qr_for_requester(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the owner's generated QR image to the intended requester.

    The requester cannot generate a QR or retrieve another user's QR.
    """

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not active.",
        )

    sharing_request = (
        db.query(SharingRequest)
        .filter(SharingRequest.id == request_id)
        .first()
    )

    if sharing_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sharing request not found.",
        )

    # Only the designated requester may retrieve this QR.
    if sharing_request.requester_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This QR code is not available to your account.",
        )

    if sharing_request.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The sharing request has not been accepted.",
        )

    owner = (
        db.query(User)
        .filter(User.id == sharing_request.owner_id)
        .first()
    )

    if owner is None or not owner.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The movie owner's account is not active.",
        )

    movie = (
        db.query(Movie)
        .filter(
            Movie.id == sharing_request.movie_id,
            Movie.owner_id == sharing_request.owner_id,
        )
        .first()
    )

    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The shared movie no longer exists.",
        )

    qr_token = (
        db.query(SharingQRToken)
        .filter(
            SharingQRToken.sharing_request_id == sharing_request.id,
            SharingQRToken.used_at.is_(None),
            SharingQRToken.revoked.is_(False),
            SharingQRToken.expires_at > func.now(),
            SharingQRToken.encrypted_token.is_not(None),
        )
        .order_by(SharingQRToken.created_at.desc())
        .first()
    )

    if qr_token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active QR code is available yet.",
        )

    try:
        cipher = get_qr_cipher()

        raw_token = cipher.decrypt(
            qr_token.encrypted_token.encode("utf-8")
        ).decode("utf-8")

    except (InvalidToken, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The QR code could not be retrieved.",
        )

    # Verify that the decrypted value matches the stored hash.
    calculated_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    if not secrets.compare_digest(
        calculated_hash,
        qr_token.token_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="QR token verification failed.",
        )

    qr_image = qrcode.make(raw_token)

    image_buffer = io.BytesIO()
    qr_image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    return StreamingResponse(
        image_buffer,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
# 6. VALIDATE AND REDEEM A QR TOKEN
# --------------------------------------------------

@router.post("/qr/validate")
def validate_sharing_qr(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Validate and redeem a one-time QR token.

    A successful redemption creates a 24-hour movie access grant.
    Only the token hash is stored in the database.
    """

    # 1. Verify that the requester is active.
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not active.",
        )

    # 2. Hash the supplied token.
    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    try:
        # 3. Look up the token without consuming it.
        qr_token = (
            db.query(SharingQRToken)
            .filter(
                SharingQRToken.token_hash == token_hash,
                SharingQRToken.used_at.is_(None),
                SharingQRToken.revoked.is_(False),
                SharingQRToken.expires_at > func.now(),
            )
            .first()
        )

        if qr_token is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "QR token is invalid, expired, revoked, "
                    "or already used."
                ),
            )

        # 4. Lock the sharing request while validating it.
        sharing_request = (
            db.query(SharingRequest)
            .filter(
                SharingRequest.id == qr_token.sharing_request_id
            )
            .with_for_update()
            .first()
        )

        if sharing_request is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The sharing request no longer exists.",
            )

        # 5. Confirm the sharing request is still accepted.
        if sharing_request.status != "accepted":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This sharing request is no longer accepted.",
            )

        # 6. Only the approved requester can redeem this token.
        if sharing_request.requester_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This QR token belongs to another user.",
            )

        # 7. Confirm the owner is active.
        owner = (
            db.query(User)
            .filter(User.id == sharing_request.owner_id)
            .first()
        )

        if owner is None or not owner.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The movie owner's account is not active.",
            )

        # 8. Confirm the movie still exists and belongs to this owner.
        movie = (
            db.query(Movie)
            .filter(
                Movie.id == sharing_request.movie_id,
                Movie.owner_id == sharing_request.owner_id,
            )
            .first()
        )

        if movie is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The shared movie no longer exists.",
            )

        # 9. Atomically consume the token.
        # This prevents two concurrent requests from redeeming it.
        result = db.execute(
            update(SharingQRToken)
            .where(
                SharingQRToken.id == qr_token.id,
                SharingQRToken.used_at.is_(None),
                SharingQRToken.revoked.is_(False),
                SharingQRToken.expires_at > func.now(),
            )
            .values(used_at=func.now())
            .returning(SharingQRToken.id)
        )

        consumed_token = result.scalar_one_or_none()

        if consumed_token is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "QR token is expired or has already been used."
                ),
            )

        # 10. Prevent duplicate grants for this sharing request.
        grant = (
            db.query(MovieAccessGrant)
            .filter(
                MovieAccessGrant.sharing_request_id
                == sharing_request.id
            )
            .first()
        )

        now = datetime.now(timezone.utc)
        grant_expires_at = now + timedelta(hours=24)

        if grant is None:
            grant = MovieAccessGrant(
                user_id=current_user.id,
                movie_id=movie.id,
                sharing_request_id=sharing_request.id,
                expires_at=grant_expires_at,
                revoked=False,
            )
            db.add(grant)
        else:
            # An existing grant may be renewed by a fresh,
            # valid QR token for the same accepted request.
            if (
                grant.user_id != current_user.id
                or grant.movie_id != movie.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="The existing access grant is inconsistent.",
                )

            grant.expires_at = grant_expires_at
            grant.revoked = False

        # 11. Save token consumption and grant creation together.
        db.commit()

        return {
            "message": "QR token validated successfully.",
            "access_granted": True,
            "access_expires_at": grant_expires_at.isoformat(),
            "movie": {
                "id": movie.id,
                "title": movie.title,
                "description": movie.description,
            },
            "token_used": True,
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not validate the QR token.",
        )




# --------------------------------------------------
# 7. REDEEM THE QR FROM THE REQUESTER'S DASHBOARD
# --------------------------------------------------

@router.post("/requests/{request_id}/redeem")
def redeem_sharing_request_qr(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Redeem the active QR token for the authenticated requester.

    The raw token never leaves the backend through this endpoint.
    Access is granted only to the requester associated with the
    accepted sharing request.
    """

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not active.",
        )

    try:
        # Find and lock the sharing request.
        sharing_request = (
            db.query(SharingRequest)
            .filter(SharingRequest.id == request_id)
            .with_for_update()
            .first()
        )

        if sharing_request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sharing request not found.",
            )

        # Only the intended requester can redeem this request.
        if sharing_request.requester_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot redeem this sharing request.",
            )

        if sharing_request.status != "accepted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The sharing request has not been accepted.",
            )

        # Confirm that the owner is active.
        owner = (
            db.query(User)
            .filter(User.id == sharing_request.owner_id)
            .first()
        )

        if owner is None or not owner.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The movie owner's account is not active.",
            )

        # Confirm that the movie still belongs to the owner.
        movie = (
            db.query(Movie)
            .filter(
                Movie.id == sharing_request.movie_id,
                Movie.owner_id == sharing_request.owner_id,
            )
            .first()
        )

        if movie is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The shared movie no longer exists.",
            )

        # Find the current active QR token.
        qr_token = (
            db.query(SharingQRToken)
            .filter(
                SharingQRToken.sharing_request_id == sharing_request.id,
                SharingQRToken.used_at.is_(None),
                SharingQRToken.revoked.is_(False),
                SharingQRToken.expires_at > func.now(),
                SharingQRToken.encrypted_token.is_not(None),
            )
            .order_by(SharingQRToken.created_at.desc())
            .with_for_update()
            .first()
        )

        if qr_token is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No active QR code is available. "
                    "Ask the owner to generate a new one."
                ),
            )

        # Decrypt the token only inside the backend.
        cipher = get_qr_cipher()

        try:
            raw_token = cipher.decrypt(
                qr_token.encrypted_token.encode("utf-8")
            ).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The QR token could not be verified.",
            )

        # Verify the decrypted token against the stored hash.
        calculated_hash = hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()

        if not secrets.compare_digest(
            calculated_hash,
            qr_token.token_hash,
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="QR token verification failed.",
            )

        # Atomically consume the token.
        result = db.execute(
            update(SharingQRToken)
            .where(
                SharingQRToken.id == qr_token.id,
                SharingQRToken.used_at.is_(None),
                SharingQRToken.revoked.is_(False),
                SharingQRToken.expires_at > func.now(),
            )
            .values(used_at=func.now())
            .returning(SharingQRToken.id)
        )

        consumed_token_id = result.scalar_one_or_none()

        if consumed_token_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This QR code has expired or has already been used.",
            )

        # Create or renew the requester's access grant.
        grant = (
            db.query(MovieAccessGrant)
            .filter(
                MovieAccessGrant.sharing_request_id == sharing_request.id
            )
            .first()
        )

        grant_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        if grant is None:
            grant = MovieAccessGrant(
                user_id=current_user.id,
                movie_id=movie.id,
                sharing_request_id=sharing_request.id,
                expires_at=grant_expires_at,
                revoked=False,
            )
            db.add(grant)
        else:
            if (
                grant.user_id != current_user.id
                or grant.movie_id != movie.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="The existing access grant is inconsistent.",
                )

            grant.expires_at = grant_expires_at
            grant.revoked = False

        db.commit()

        return {
            "message": "QR redeemed successfully. Movie access granted.",
            "access_granted": True,
            "access_expires_at": grant_expires_at.isoformat(),
            "movie": {
                "id": movie.id,
                "title": movie.title,
                "description": movie.description,
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not redeem the sharing QR code.",
        )

    