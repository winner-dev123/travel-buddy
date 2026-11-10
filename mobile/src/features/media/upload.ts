import * as Crypto from 'expo-crypto';
import { File, UploadType } from 'expo-file-system';
import * as ImagePicker from 'expo-image-picker';

import type { ApiClient } from '@/api';

/** Contract `MediaPurpose`. */
export type MediaPurpose = 'post' | 'avatar' | 'message' | 'group_cover' | 'challenge';

/** A photo chosen on the device; ``mediaId`` is set once it reached the server, so a retried
 * publish never uploads the same photo twice. */
export interface DraftPhoto {
  uri: string;
  width: number;
  height: number;
  mimeType: string;
  mediaId?: string;
}

interface MediaUpload {
  media_id: string;
  upload: { method: 'PUT'; url: string; headers: Record<string, string>; expires_at: string };
  max_bytes: number;
}

/** Types the server re-encodes into safe variants (HEIC is accepted but cannot be processed). */
const PROCESSABLE: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
};
export const MAX_PHOTOS = 10;

export class UnsupportedPhotoError extends Error {}
export class PhotoUploadError extends Error {}

function mimeOf(asset: ImagePicker.ImagePickerAsset): string | null {
  const declared = asset.mimeType?.toLowerCase();
  if (declared && Object.values(PROCESSABLE).includes(declared)) return declared;
  const extension = (asset.fileName ?? asset.uri).split('.').pop()?.toLowerCase() ?? '';
  return PROCESSABLE[extension] ?? null;
}

function toDraft(assets: ImagePicker.ImagePickerAsset[]): DraftPhoto[] {
  const photos = assets.flatMap((asset) => {
    const mimeType = mimeOf(asset);
    return mimeType && asset.type !== 'video'
      ? [{ uri: asset.uri, width: asset.width, height: asset.height, mimeType }]
      : [];
  });
  if (photos.length < assets.length) throw new UnsupportedPhotoError();
  return photos;
}

const PICKER_OPTIONS: ImagePicker.ImagePickerOptions = {
  mediaTypes: ['images'],
  quality: 0.85, // re-encode: also strips most camera metadata before upload
  exif: false,
  // iOS hands over JPEG instead of HEIC, which the server cannot process yet.
  preferredAssetRepresentationMode:
    ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible,
};

/** The system photo picker needs no library permission (it only returns what the user picks). */
export async function pickPhotos(remaining: number): Promise<DraftPhoto[]> {
  if (remaining <= 0) return [];
  const result = await ImagePicker.launchImageLibraryAsync({
    ...PICKER_OPTIONS,
    allowsMultipleSelection: remaining > 1,
    selectionLimit: remaining,
  });
  return result.canceled ? [] : toDraft(result.assets.slice(0, remaining));
}

/** The camera asks for permission in context, the first time it is used. */
export async function takePhoto(): Promise<DraftPhoto[] | 'denied'> {
  const permission = await ImagePicker.requestCameraPermissionsAsync();
  if (!permission.granted) return 'denied';
  const result = await ImagePicker.launchCameraAsync(PICKER_OPTIONS);
  return result.canceled ? [] : toDraft(result.assets);
}

function hex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** POST-002: presigned upload. Declare size and hash, PUT the bytes to quarantine storage, then
 * finalize; the server scans and re-encodes before anyone else can see the photo. */
export async function uploadPhoto(
  client: ApiClient,
  photo: DraftPhoto,
  purpose: MediaPurpose = 'post',
): Promise<string> {
  const file = new File(photo.uri);
  const bytes = await file.bytes();
  const sha256 = hex(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes));
  const target = await client.post<MediaUpload>('/v1/media/uploads', {
    body: {
      purpose,
      mime_type: photo.mimeType,
      bytes: bytes.byteLength,
      sha256,
      ...(photo.width > 0 && photo.height > 0 ? { width: photo.width, height: photo.height } : {}),
    },
  });
  const sent = await file.upload(target.upload.url, {
    httpMethod: 'PUT',
    uploadType: UploadType.BINARY_CONTENT,
    headers: target.upload.headers,
  });
  if (sent.status < 200 || sent.status >= 300) throw new PhotoUploadError(String(sent.status));
  await client.post(`/v1/media/${target.media_id}/finalize`);
  return target.media_id;
}
