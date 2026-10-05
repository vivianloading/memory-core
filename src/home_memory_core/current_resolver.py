    v0.1 reports ADMISSION_PROOF_UNAVAILABLE rather than guessing across the
    process boundary.
    """

    def __init__(
        self,
        *,
        admission_authority: CurrentAdmissionAuthority,
        _marker: object,
    ) -> None:
        if _marker is not _CURRENT_RESOLVER_MARKER:
            raise CurrentResolverError(
                "CurrentResolver must be opened through HOME"
            )
        if not isinstance(admission_authority, CurrentAdmissionAuthority):
            raise TypeError(
                "admission_authority must be CurrentAdmissionAuthority"
            )
        admission_authority._assert_live_authority_binding()
        self._admission_authority = admission_authority
        self._canonical_db_path = Path(
            admission_authority._canonical_db_path
        ).resolve()

    def resolve_key(
        self,
        *,
        namespace: CurrentNamespace,
        owner_id: str,
        key: str,
        as_of: datetime,
    ) -> CurrentResolverDecision:
        _validate_request(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            as_of=as_of,
        )
        self._assert_live_binding()
        connection = self._read_connection()
        try:
            receipts = (
                self._admission_authority
                ._snapshot_live_receipts_for_resolution(
                    connection=connection,
                )
            )
            missing = _missing_live_admission_effects(
                connection=connection,
                namespace=namespace,
                owner_id=owner_id,
                key=key,
                as_of=as_of,
                receipts=receipts,
            )
            if missing:
                return CurrentResolverDecision(
                    namespace=namespace,
                    owner_id=owner_id,
                    key=key,
                    as_of=as_of,
                    status=(
                        CurrentResolverStatus.ADMISSION_PROOF_UNAVAILABLE
                    ),
                    semantic_resolution=None,
                    dependencies=(),
                    blocks=(),
                    missing_live_admission_effects=missing,
                    reason_codes=("LIVE_ADMISSION_PROOF_UNAVAILABLE",),
                )

            records, end_events = _read_live_admitted_history(
                connection=connection,
                receipts=receipts,
            )
            return _resolve_key_in_connection(
                connection=connection,
                namespace=namespace,
                owner_id=owner_id,
                key=key,
                as_of=as_of,
                records=records,
                end_events=end_events,
            )
        finally:
            connection.close()

    def resolve_owner(
        self,
        *,
        namespace: CurrentNamespace,
        owner_id: str,
        as_of: datetime,
    ) -> CurrentResolvedView:
        _validate_owner_request(
            namespace=namespace,
            owner_id=owner_id,
            as_of=as_of,
        )
        self._assert_live_binding()
        connection = self._read_connection()
        try:
            return CurrentResolver._resolve_owner_in_connection(
                self,
                connection=connection,
                namespace=namespace,
                owner_id=owner_id,
                as_of=as_of,
            )
        finally:
            connection.close()

    def _resolve_owner_in_connection(
        self,
        *,
        connection: sqlite3.Connection,
        namespace: CurrentNamespace,
        owner_id: str,
        as_of: datetime,
    ) -> CurrentResolvedView:
        """Resolve one owner on an already-pinned HOME read snapshot.

        This package-internal seam exists for higher-level operations such as
        Wake issuance that must combine Living and Current reads from one SQLite
        transaction. It does not weaken live admission proof or create a new
        public resolver path.
        """

        _validate_owner_request(
            namespace=namespace,
            owner_id=owner_id,
            as_of=as_of,
        )
        self._assert_live_binding()
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be sqlite3.Connection")
        if not connection.in_transaction:
            raise CurrentResolverError(
                "in-connection Current resolution requires an active read transaction"
            )
        assert_current_admission_schema(connection)
        assert_current_admission_data_integrity(connection)
        assert_source_suppression_ledger(connection)
        receipts = (
            self._admission_authority
            ._snapshot_live_receipts_for_resolution(
                connection=connection,
            )
        )
        keys = _operational_keys(
            connection=connection,
            namespace=namespace,
            owner_id=owner_id,
            as_of=as_of,
        )
        items = tuple(
            CurrentResolver._resolve_key_with_receipts(
                self,
                connection=connection,
                receipts=receipts,
                namespace=namespace,
                owner_id=owner_id,
                key=key,
                as_of=as_of,
            )
            for key in keys
        )
        return CurrentResolvedView(
            as_of=as_of,
            namespace=namespace,
            owner_id=owner_id,
            items=items,
        )

    def _resolve_key_with_receipts(
        self,
        *,
        connection: sqlite3.Connection,
        receipts: tuple[CurrentAdmissionReceipt, ...],
        namespace: CurrentNamespace,
        owner_id: str,
        key: str,
        as_of: datetime,
    ) -> CurrentResolverDecision:
        missing = _missing_live_admission_effects(
            connection=connection,
            namespace=namespace,