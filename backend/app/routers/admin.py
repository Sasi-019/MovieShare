from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Movie, User
from app.routers.routes import get_current_user


router = APIRouter(
    prefix="/admin",
    tags=["Administration"],
)


# --------------------------------------------------
# 1. VERIFY ADMINISTRATOR PERMISSIONS
# --------------------------------------------------

def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Allow access only to active administrator accounts."""

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )

    return current_user


# --------------------------------------------------
# 2. ADMIN DASHBOARD STATISTICS
# --------------------------------------------------

@router.get("/dashboard")
def admin_dashboard(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return overall MovieShare statistics."""

    total_users = db.query(User).count()
    total_movies = db.query(Movie).count()

    storage_used = (
        db.query(func.coalesce(func.sum(Movie.file_size), 0))
        .scalar()
    )

    return {
        "message": "Administrator dashboard data",
        "admin": {
            "id": admin.id,
            "name": admin.name,
            "email": admin.email,
        },
        "statistics": {
            "total_users": total_users,
            "total_movies": total_movies,
            "total_storage_bytes": int(storage_used),
        },
    }


# --------------------------------------------------
# 3. LIST ALL USERS AND THEIR CONTRIBUTIONS
# --------------------------------------------------

@router.get("/users")
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return all users with their movie counts and storage usage."""

    user_statistics = (
        db.query(
            User.id,
            User.name,
            User.email,
            User.role,
            User.is_active,
            User.created_at,
            func.count(Movie.id).label("movies_uploaded"),
            func.coalesce(
                func.sum(Movie.file_size),
                0,
            ).label("storage_used_bytes"),
        )
        .outerjoin(
            Movie,
            Movie.owner_id == User.id,
        )
        .group_by(
            User.id,
            User.name,
            User.email,
            User.role,
            User.is_active,
            User.created_at,
        )
        .order_by(User.created_at.desc())
        .all()
    )

    users = []

    for user in user_statistics:
        users.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at,
                "movies_uploaded": user.movies_uploaded,
                "storage_used_bytes": int(
                    user.storage_used_bytes or 0
                ),
            }
        )

    return {
        "total": len(users),
        "users": users,
    }


# --------------------------------------------------
# 4. BLOCK A USER
# --------------------------------------------------

@router.patch("/users/{user_id}/block")
def block_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Block a regular user from accessing MovieShare."""

    target_user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if target_user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot block your own administrator account",
        )

    if target_user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator accounts cannot be blocked through this endpoint",
        )

    if not target_user.is_active:
        return {
            "message": "User is already blocked",
            "user_id": target_user.id,
            "is_active": False,
        }

    target_user.is_active = False

    try:
        db.commit()
        db.refresh(target_user)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to block user",
        )

    return {
        "message": "User blocked successfully",
        "user_id": target_user.id,
        "is_active": target_user.is_active,
    }


# --------------------------------------------------
# 5. UNBLOCK A USER
# --------------------------------------------------

@router.patch("/users/{user_id}/unblock")
def unblock_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Restore access for a blocked regular user."""

    target_user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if target_user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own administrator account status",
        )

    if target_user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator accounts cannot be managed through this endpoint",
        )

    if target_user.is_active:
        return {
            "message": "User is already active",
            "user_id": target_user.id,
            "is_active": True,
        }

    target_user.is_active = True

    try:
        db.commit()
        db.refresh(target_user)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unblock user",
        )

    return {
        "message": "User unblocked successfully",
        "user_id": target_user.id,
        "is_active": target_user.is_active,
    }