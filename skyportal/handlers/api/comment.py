import string
import base64
from marshmallow.exceptions import ValidationError
from baselayer.app.custom_exceptions import AccessError
from baselayer.app.access import permissions, auth_or_token
from baselayer.log import make_log
from ..base import BaseHandler
import sqlalchemy as sa
import time
from ...utils.sizeof import sizeof, SIZE_WARNING_THRESHOLD
from ...models import (
    Comment,
    CommentOnSpectrum,
    CommentOnGCN,
    CommentOnShift,
    Spectrum,
    GcnEvent,
    Shift,
    Group,
    User,
    UserNotification,
    Token,
)

log = make_log('api/comment')


def users_mentioned(text, session):
    punctuation = string.punctuation.replace("-", "").replace("@", "")
    usernames = []
    for word in text.replace(",", " ").split():
        word = word.strip(punctuation)
        if word.startswith("@"):
            usernames.append(word.replace("@", ""))
    users = session.scalars(
        User.select(session.user_or_token).where(
            User.username.in_(usernames),
            User.preferences["notifications"]["mention"]["active"]
            .astext.cast(sa.Boolean)
            .is_(True),
        )
    ).all()

    return users


class CommentHandler(BaseHandler):
    @auth_or_token
    def get(self, associated_resource_type, resource_id, comment_id=None):
        """
        ---
        single:
          description: Retrieve a comment
          tags:
            - comments
            - sources
            - spectra
          parameters:
            - in: path
              name: associated_resource_type
              required: true
              schema:
                type: string
              description: |
                 What underlying data the comment is on:
                 "sources" or "spectra" or "gcn_event".
            - in: path
              name: resource_id
              required: true
              schema:
                type: string
                enum: [sources, spectra, gcn_event]
              description: |
                 The ID of the source, spectrum, or gcn_event
                 that the comment is posted to.
                 This would be a string for a source ID
                 or an integer for a spectrum or gcn_event
            - in: path
              name: comment_id
              required: true
              schema:
                type: integer

          responses:
            200:
              content:
                application/json:
                  schema: SingleComment
            400:
              content:
                application/json:
                  schema: Error
        multiple:
          description: Retrieve all comments associated with specified resource
          tags:
            - comments
            - spectra
            - sources
            - gcn_event
          parameters:
            - in: path
              name: associated_resource_type
              required: true
              schema:
                type: string
                enum: [sources]
              description: |
                 What underlying data the comment is on, e.g., "sources"
                 or "spectra" or "gcn_event".
            - in: path
              name: resource_id
              required: true
              schema:
                type: string
              description: |
                 The ID of the underlying data.
                 This would be a string for a source ID
                 or an integer for other data types like spectrum or gcn_event.
          responses:
            200:
              content:
                application/json:
                  schema: ArrayOfComments
            400:
              content:
                application/json:
                  schema: Error
        """

        start = time.time()

        with self.Session() as session:
            if comment_id is None:
                if associated_resource_type.lower() == "sources":
                    comments = (
                        session.scalars(
                            Comment.select(self.current_user).where(
                                Comment.obj_id == resource_id
                            )
                        )
                        .unique()
                        .all()
                    )
                elif associated_resource_type.lower() == "spectra":
                    comments = (
                        session.scalars(
                            CommentOnSpectrum.select(self.current_user).where(
                                CommentOnSpectrum.spectrum_id == resource_id
                            )
                        )
                        .unique()
                        .all()
                    )
                elif associated_resource_type.lower() == "gcn_event":
                    comments = (
                        session.scalars(
                            CommentOnGCN.select(self.current_user).where(
                                CommentOnGCN.gcn_id == resource_id
                            )
                        )
                        .unique()
                        .all()
                    )
                elif associated_resource_type.lower() == "shift":
                    comments = (
                        session.scalars(
                            CommentOnShift.select(self.current_user).where(
                                CommentOnShift.shift_id == resource_id
                            )
                        )
                        .unique()
                        .all()
                    )
                else:
                    return self.error(
                        f'Unsupported associated resource type "{associated_resource_type}".'
                    )

                query_output = [c.to_dict() for c in comments]
                query_size = sizeof(query_output)
                if query_size >= SIZE_WARNING_THRESHOLD:
                    end = time.time()
                    duration = end - start
                    log(
                        f'User {self.associated_user_object.id} comment query returned {query_size} bytes in {duration} seconds'
                    )

                return self.success(data=query_output)

            try:
                comment_id = int(comment_id)
            except (TypeError, ValueError):
                return self.error("Must provide a valid (scalar integer) comment ID. ")

            # the default is to comment on an object
            if associated_resource_type.lower() == "sources":
                comment = session.scalars(
                    Comment.select(self.current_user).where(Comment.id == comment_id)
                ).first()
                if comment is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(comment.obj_id)

            elif associated_resource_type.lower() == "spectra":
                comment = session.scalars(
                    CommentOnSpectrum.select(self.current_user).where(
                        CommentOnSpectrum.id == comment_id
                    )
                ).first()
                if comment is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(comment.spectrum_id)
            elif associated_resource_type.lower() == "gcn_event":
                comment = session.scalars(
                    CommentOnGCN.select(self.current_user).where(
                        CommentOnGCN.id == comment_id
                    )
                ).first()
                if comment is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(comment.gcn_id)
            elif associated_resource_type.lower() == "shift":
                comment = session.scalars(
                    CommentOnShift.select(self.current_user).where(
                        CommentOnShift.id == comment_id
                    )
                ).first()
                if comment is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(comment.shift_id)
            # add more options using elif
            else:
                return self.error(
                    f'Unsupported associated_resource_type "{associated_resource_type}".'
                )

            if comment_resource_id_str != resource_id:
                return self.error(
                    f'Comment resource ID does not match resource ID given in path ({resource_id})'
                )

            comment_data = comment.to_dict()
            query_size = sizeof(comment_data)
            if query_size >= SIZE_WARNING_THRESHOLD:
                end = time.time()
                duration = end - start
                log(
                    f'User {self.associated_user_object.id} source query returned {query_size} bytes in {duration} seconds'
                )

            return self.success(data=comment_data)

    @permissions(['Comment'])
    def post(self, associated_resource_type, resource_id):
        """
        ---
        description: Post a comment
        tags:
          - comments
        parameters:
          - in: path
            name: associated_resource_type
            required: true
            schema:
              type: string
              enum: [sources, spectrum, gcn_event]
            description: |
               What underlying data the comment is on:
               "source" or "spectrum" or "gcn_event".
          - in: path
            name: resource_id
            required: true
            schema:
              type: string
              enum: [sources, spectra, gcn_event]
            description: |
               The ID of the source or spectrum
               that the comment is posted to.
               This would be a string for a source ID
               or an integer for a spectrum.
        requestBody:
          content:
            application/json:
              schema:
                type: object
                properties:
                  text:
                    type: string
                  group_ids:
                    type: array
                    items:
                      type: integer
                    description: |
                      List of group IDs corresponding to which groups should be
                      able to view comment. Defaults to all of requesting user's
                      groups.
                  attachment:
                    type: object
                    properties:
                      body:
                        type: string
                        format: byte
                        description: base64-encoded file contents
                      name:
                        type: string

                required:
                  - text
        responses:
          200:
            content:
              application/json:
                schema:
                  allOf:
                    - $ref: '#/components/schemas/Success'
                    - type: object
                      properties:
                        data:
                          type: object
                          properties:
                            comment_id:
                              type: integer
                              description: New comment ID
        """
        data = self.get_json()

        comment_text = data.get("text")

        if 'attachment' in data:
            if (
                isinstance(data['attachment'], dict)
                and 'body' in data['attachment']
                and 'name' in data['attachment']
            ):
                attachment_bytes = str.encode(
                    data['attachment']['body'].split('base64,')[-1]
                )
                attachment_name = data['attachment']['name']
            else:
                return self.error("Malformed comment attachment")
        else:
            attachment_bytes, attachment_name = None, None

        author = self.associated_user_object
        is_bot_request = isinstance(self.current_user, Token)

        with self.Session() as session:
            group_ids = data.pop('group_ids', None)
            if not group_ids:
                group_ids = [g.id for g in self.current_user.accessible_groups]
            groups = session.scalars(
                Group.select(self.current_user).where(Group.id.in_(group_ids))
            ).all()
            if {g.id for g in groups} != set(group_ids):
                return self.error(
                    f'Cannot find one or more groups with IDs: {group_ids}.'
                )

            if associated_resource_type.lower() == "sources":
                obj_id = resource_id
                comment = Comment(
                    text=comment_text,
                    obj_id=obj_id,
                    attachment_bytes=attachment_bytes,
                    attachment_name=attachment_name,
                    author=author,
                    groups=groups,
                    bot=is_bot_request,
                )
            elif associated_resource_type.lower() == "spectra":
                spectrum_id = resource_id
                spectrum = session.scalars(
                    Spectrum.select(self.current_user).where(Spectrum.id == spectrum_id)
                ).first()
                if spectrum is None:
                    return self.error(
                        f'Could not find any accessible spectra with ID {spectrum_id}.'
                    )
                comment = CommentOnSpectrum(
                    text=comment_text,
                    spectrum_id=spectrum_id,
                    attachment_bytes=attachment_bytes,
                    attachment_name=attachment_name,
                    author=author,
                    groups=groups,
                    bot=is_bot_request,
                    obj_id=spectrum.obj_id,
                )

            elif associated_resource_type.lower() == "gcn_event":
                gcnevent_id = resource_id
                gcn_event = session.scalars(
                    GcnEvent.select(self.current_user).where(GcnEvent.id == gcnevent_id)
                ).first()
                if gcn_event is None:
                    return self.error(
                        f'Could not find any accessible gcn events with ID {gcnevent_id}.'
                    )
                comment = CommentOnGCN(
                    text=comment_text,
                    gcn_id=gcn_event.id,
                    attachment_bytes=attachment_bytes,
                    attachment_name=attachment_name,
                    author=author,
                    groups=groups,
                    bot=is_bot_request,
                )
            elif associated_resource_type.lower() == "shift":
                shift_id = resource_id
                try:
                    shift = Shift.get_if_accessible_by(
                        shift_id, self.current_user, raise_if_none=True
                    )
                except AccessError:
                    return self.error(f'Could not access Shift {shift.id}.', status=403)
                comment = CommentOnShift(
                    text=comment_text,
                    shift_id=shift.id,
                    attachment_bytes=attachment_bytes,
                    attachment_name=attachment_name,
                    author=author,
                    groups=groups,
                    bot=is_bot_request,
                )
            else:
                return self.error(
                    f'Unknown resource type "{associated_resource_type}".'
                )

            users_mentioned_in_comment = users_mentioned(comment_text, session)
            if associated_resource_type.lower() == "sources":
                text_to_send = f"*@{self.associated_user_object.username}* mentioned you in a comment on *{obj_id}*"
                url_endpoint = f"/source/{obj_id}"
            elif associated_resource_type.lower() == "spectra":
                text_to_send = f"*@{self.associated_user_object.username}* mentioned you in a comment on *{spectrum_id}*"
                url_endpoint = f"/source/{spectrum_id}"
            elif associated_resource_type.lower() == "gcn_event":
                text_to_send = f"*@{self.associated_user_object.username}* mentioned you in a comment on *{gcnevent_id}*"
                url_endpoint = f"/gcn_events/{gcnevent_id}"
            elif associated_resource_type.lower() == "shift":
                text_to_send = f"*@{self.associated_user_object.username}* mentioned you in a comment on *shift {shift_id}*"
                url_endpoint = "/shifts"
            else:
                return self.error(
                    f'Unknown resource type "{associated_resource_type}".'
                )

            if users_mentioned_in_comment:
                for user_mentioned in users_mentioned_in_comment:
                    session.add(
                        UserNotification(
                            user=user_mentioned,
                            text=text_to_send,
                            notification_type="mention",
                            url=url_endpoint,
                        )
                    )

            session.add(comment)
            session.commit()
            if users_mentioned_in_comment:
                for user_mentioned in users_mentioned_in_comment:
                    self.flow.push(
                        user_mentioned.id, "skyportal/FETCH_NOTIFICATIONS", {}
                    )

            if hasattr(
                comment, 'obj'
            ):  # comment on object, or object related resources
                self.push_all(
                    action='skyportal/REFRESH_SOURCE',
                    payload={'obj_key': comment.obj.internal_key},
                )

            if isinstance(comment, CommentOnGCN):
                self.push_all(
                    action='skyportal/REFRESH_GCNEVENT',
                    payload={'gcnEvent_dateobs': comment.gcn.dateobs},
                )
            elif isinstance(comment, CommentOnSpectrum):
                self.push_all(
                    action='skyportal/REFRESH_SOURCE_SPECTRA',
                    payload={'obj_internal_key': comment.obj.internal_key},
                )
            elif isinstance(comment, CommentOnShift):
                self.push_all(
                    action='skyportal/REFRESH_SHIFTS',
                    payload={'shift_id': comment.shift_id},
                )

            return self.success(data={'comment_id': comment.id})

    @permissions(['Comment'])
    def put(self, associated_resource_type, resource_id, comment_id):
        """
        ---
        description: Update a comment
        tags:
          - comments
        parameters:
          - in: path
            name: associated_resource_type
            required: true
            schema:
              type: string
              enum: [sources, spectrum, gcn_event, shift]
            description: |
               What underlying data the comment is on:
               "sources" or "spectra" or "gcn_event" or "shift".
          - in: path
            name: resource_id
            required: true
            schema:
              type: string
              enum: [sources, spectra, gcn_event, shift]
            description: |
               The ID of the source or spectrum
               that the comment is posted to.
               This would be a string for an object ID
               or an integer for a spectrum, gcn_event or shift.
          - in: path
            name: comment_id
            required: true
            schema:
              type: integer
        requestBody:
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/CommentNoID'
                  - type: object
                    properties:
                      group_ids:
                        type: array
                        items:
                          type: integer
                        description: |
                          List of group IDs corresponding to which groups should be
                          able to view comment.
        responses:
          200:
            content:
              application/json:
                schema: Success
          400:
            content:
              application/json:
                schema: Error
        """

        try:
            comment_id = int(comment_id)
        except (TypeError, ValueError):
            return self.error("Must provide a valid (scalar integer) comment ID. ")

        with self.Session() as session:

            if associated_resource_type.lower() == "sources":
                schema = Comment.__schema__()
                c = session.scalars(
                    Comment.select(self.current_user, mode="update").where(
                        Comment.id == comment_id
                    )
                ).first()
                if c is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(c.obj_id)

            elif associated_resource_type.lower() == "spectra":
                schema = CommentOnSpectrum.__schema__()
                c = session.scalars(
                    CommentOnSpectrum.select(self.current_user, mode="update").where(
                        CommentOnSpectrum.id == comment_id
                    )
                ).first()
                if c is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(c.spectrum_id)

            elif associated_resource_type.lower() == "gcn_event":
                schema = CommentOnGCN.__schema__()
                c = session.scalars(
                    CommentOnGCN.select(self.current_user, mode="update").where(
                        CommentOnGCN.id == comment_id
                    )
                ).first()
                if c is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(c.gcn_id)
            elif associated_resource_type.lower() == "shift":
                schema = CommentOnShift.__schema__()
                c = session.scalars(
                    CommentOnShift.select(self.current_user, mode="update").where(
                        CommentOnShift.id == comment_id
                    )
                ).first()
                if c is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(c.shift_id)
            # add more options using elif
            else:
                return self.error(
                    f'Unsupported associated_resource_type "{associated_resource_type}".'
                )

            data = self.get_json()
            group_ids = data.pop("group_ids", None)
            data['id'] = comment_id
            attachment_bytes = data.pop('attachment_bytes', None)

            try:
                schema.load(data, partial=True)
            except ValidationError as e:
                return self.error(
                    f'Invalid/missing parameters: {e.normalized_messages()}'
                )

            if 'text' in data:
                c.text = data['text']

            if 'attachment_name' in data:
                c.attachment_name = data['attachment_name']

            if attachment_bytes is not None:
                attachment_bytes = str.encode(attachment_bytes.split('base64,')[-1])
                c.attachment_bytes = attachment_bytes

            bytes_is_none = c.attachment_bytes is None
            name_is_none = c.attachment_name is None

            if bytes_is_none ^ name_is_none:
                return self.error(
                    'This update leaves one of attachment name or '
                    'attachment bytes null. Both fields must be '
                    'filled, or both must be null.'
                )

            if group_ids is not None:
                groups = session.scalars(
                    Group.select(self.current_user).where(Group.id.in_(group_ids))
                ).all()
                if {g.id for g in groups} != set(group_ids):
                    return self.error(
                        f'Cannot find one or more groups with IDs: {group_ids}.'
                    )
                c.groups = groups

            if comment_resource_id_str != resource_id:
                return self.error(
                    f'Comment resource ID does not match resource ID given in path ({resource_id})'
                )

            session.add(c)
            session.commit()

            if hasattr(c, 'obj'):  # comment on object, or object related resources
                self.push_all(
                    action='skyportal/REFRESH_SOURCE',
                    payload={'obj_key': c.obj.internal_key},
                )
            if isinstance(c, CommentOnSpectrum):  # also update the spectrum
                self.push_all(
                    action='skyportal/REFRESH_SOURCE_SPECTRA',
                    payload={'obj_internal_key': c.obj.internal_key},
                )
            elif isinstance(c, CommentOnGCN):  # also update the gcn
                self.push_all(
                    action='skyportal/REFRESH_SOURCE_GCN',
                    payload={'obj_internal_key': c.obj.internal_key},
                )
            elif isinstance(c, CommentOnShift):  # also update the shift
                self.push_all(
                    action='skyportal/REFRESH_SHIFT',
                    payload={'obj_internal_key': c.obj.internal_key},
                )

            return self.success()

    @permissions(['Comment'])
    def delete(self, associated_resource_type, resource_id, comment_id):
        """
        ---
        description: Delete a comment
        tags:
          - comments
        parameters:
          - in: path
            name: associated_resource_type
            required: true
            schema:
              type: string
            description: |
               What underlying data the comment is on:
               "sources" or "spectra".
          - in: path
            name: resource_id
            required: true
            schema:
              type: string
              enum: [sources, spectra, gcn_event]
            description: |
               The ID of the source or spectrum
               that the comment is posted to.
               This would be a string for a source ID
               or an integer for a spectrum or gcn_event.
          - in: path
            name: comment_id
            required: true
            schema:
              type: integer

        responses:
          200:
            content:
              application/json:
                schema: Success
        """

        try:
            comment_id = int(comment_id)
        except (TypeError, ValueError):
            return self.error("Must provide a valid (scalar integer) comment ID.")

        with self.Session() as session:

            if associated_resource_type.lower() == "sources":
                c = session.scalars(
                    Comment.select(self.current_user, mode="delete").where(
                        Comment.id == comment_id
                    )
                ).first()
                if c is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(c.obj_id)
            elif associated_resource_type.lower() == "spectra":
                c = session.scalars(
                    CommentOnSpectrum.select(self.current_user, mode="delete").where(
                        CommentOnSpectrum.id == comment_id
                    )
                ).first()
                if c is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(c.spectrum_id)
            elif associated_resource_type.lower() == "gcn_event":
                c = session.scalars(
                    CommentOnGCN.select(self.current_user, mode="delete").where(
                        CommentOnGCN.id == comment_id
                    )
                ).first()
                if c is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(c.gcn_id)
            elif associated_resource_type.lower() == "shift":
                c = session.scalars(
                    CommentOnShift.select(self.current_user, mode="delete").where(
                        CommentOnShift.id == comment_id
                    )
                ).first()
                if c is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(c.shift_id)

            # add more options using elif
            else:
                return self.error(
                    f'Unsupported associated_resource_type "{associated_resource_type}".'
                )

            if isinstance(c, CommentOnGCN):
                gcnevent_dateobs = c.gcn.dateobs
            elif not isinstance(c, CommentOnShift):
                obj_key = c.obj.internal_key

            if comment_resource_id_str != resource_id:
                return self.error(
                    f'Comment resource ID does not match resource ID given in path ({resource_id})'
                )

            session.delete(c)
            session.commit()

            if hasattr(c, 'obj'):  # comment on object, or object related resources
                self.push_all(
                    action='skyportal/REFRESH_SOURCE',
                    payload={'obj_key': obj_key},
                )

            if isinstance(c, CommentOnGCN):  # also update the GcnEvent
                self.push_all(
                    action='skyportal/REFRESH_GCNEVENT',
                    payload={'gcnEvent_dateobs': gcnevent_dateobs},
                )
            elif isinstance(c, CommentOnSpectrum):  # also update the spectrum
                self.push_all(
                    action='skyportal/REFRESH_SOURCE_SPECTRA',
                    payload={'obj_internal_key': obj_key},
                )
            elif isinstance(c, CommentOnShift):  # also update the shift
                self.push_all(
                    action='skyportal/REFRESH_SHIFTS',
                )

            return self.success()


class CommentAttachmentHandler(BaseHandler):
    @auth_or_token
    def get(self, associated_resource_type, resource_id, comment_id):
        """
        ---
        description: Download comment attachment
        tags:
          - comments
        parameters:
          - in: path
            name: associated_resource_type
            required: true
            schema:
              type: string
              enum: [sources, spectrum, gcn_event]
            description: |
               What underlying data the comment is on:
               "sources" or "spectra".
          - in: path
            name: resource_id
            required: true
            schema:
              type: string
              enum: [sources, spectra, gcn_event]
            description: |
               The ID of the source or spectrum
               that the comment is posted to.
               This would be a string for a source ID
               or an integer for a spectrum.
          - in: path
            name: comment_id
            required: true
            schema:
              type: integer
          - in: query
            name: download
            nullable: True
            schema:
              type: boolean
              description: If true, download the attachment; else return file data as text. True by default.
        responses:
          200:
            content:
              application:
                schema:
                  type: string
                  format: base64
                  description: base64-encoded contents of attachment
              application/json:
                schema:
                  allOf:
                    - $ref: '#/components/schemas/Success'
                    - type: object
                      properties:
                        data:
                          type: object
                          properties:
                            comment_id:
                              type: integer
                              description: Comment ID attachment came from
                            attachment:
                              type: string
                              description: The attachment file contents decoded as a string

        """

        start = time.time()

        try:
            comment_id = int(comment_id)
        except (TypeError, ValueError):
            return self.error("Must provide a valid (scalar integer) comment ID. ")

        download = self.get_query_argument('download', True)

        with self.Session() as session:

            if associated_resource_type.lower() == "sources":
                comment = session.scalars(
                    Comment.select(self.current_user).where(Comment.id == comment_id)
                ).first()
                if comment is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(comment.obj_id)

            elif associated_resource_type.lower() == "spectra":
                comment = session.scalars(
                    CommentOnSpectrum.select(self.current_user).where(
                        CommentOnSpectrum.id == comment_id
                    )
                ).first()
                if comment is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(comment.spectrum_id)

            elif associated_resource_type.lower() == "gcn_event":
                comment = session.scalars(
                    CommentOnGCN.select(self.current_user).where(
                        CommentOnGCN.id == comment_id
                    )
                ).first()
                if comment is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(comment.gcn_id)
            elif associated_resource_type.lower() == "shift":
                comment = session.scalars(
                    CommentOnShift.select(self.current_user).where(
                        CommentOnShift.id == comment_id
                    )
                ).first()
                if comment is None:
                    return self.error(
                        'Could not find any accessible comments.', status=403
                    )
                comment_resource_id_str = str(comment.shift_id)

            # add more options using elif
            else:
                return self.error(
                    f'Unsupported associated_resource_type "{associated_resource_type}".'
                )

            if comment_resource_id_str != resource_id:
                return self.error(
                    f'Comment resource ID does not match resource ID given in path ({resource_id})'
                )

            if not comment.attachment_bytes:
                return self.error('Comment has no attachment')

            if download:
                self.set_header(
                    "Content-Disposition",
                    "attachment; " f"filename={comment.attachment_name}",
                )
                self.set_header("Content-type", "application/octet-stream")
                self.write(base64.b64decode(comment.attachment_bytes))
            else:
                comment_data = {
                    "commentId": int(comment_id),
                    "attachment": base64.b64decode(comment.attachment_bytes).decode(),
                }

                query_size = sizeof(comment_data)
                if query_size >= SIZE_WARNING_THRESHOLD:
                    end = time.time()
                    duration = end - start
                    log(
                        f'User {self.associated_user_object.id} comment attachment query returned {query_size} bytes in {duration} seconds'
                    )

                return self.success(data=comment_data)
