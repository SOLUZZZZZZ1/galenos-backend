@router.get("/cases/{case_id}")
def get_guard_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = (
        db.query(GuardCase)
        .filter(GuardCase.id == case_id, GuardCase.user_id == current_user.id)
        .first()
    )
    if not c:
        raise HTTPException(404, "Not Found")

    return {
        "id": c.id,
        "title": c.title,
        "anonymized_summary": c.anonymized_summary,
        "status": c.status,
        "age_group": c.age_group,
        "sex": c.sex,
        "context": c.context,
        "created_at": c.created_at,
        "last_activity_at": c.last_activity_at,
    }
