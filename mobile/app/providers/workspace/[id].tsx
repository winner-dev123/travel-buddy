import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { showActions } from '@/components/ActionSheet';
import { Button, Notice, SwitchRow } from '@/components/Form';
import { MenuGroup, MenuRow } from '@/components/MenuRow';
import { ServerFeature } from '@/features/flags/serverFlags';
import { pickPhotos, takePhoto, uploadPhoto } from '@/features/media/upload';
import {
  addDocument,
  deactivateProvider,
  deleteDocument,
  getWorkspace,
  listDocuments,
  providerKeys,
  submitProvider,
  type DocumentKind,
  type ProviderWorkspace,
} from '@/features/providers/api';
import { ProviderLogo } from '@/features/providers/components';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-168 A provider's own workspace: verification status, documents, submit, and the way to
 * offerings, requests and the team (PROV-001..006). */
export default function WorkspaceScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <Workspace />
    </ServerFeature>
  );
}

const MISSING_KEYS = {
  display_name: 'providers.missing_.display_name',
  base_destination_id: 'providers.missing_.base_destination_id',
  languages: 'providers.missing_.languages',
  legal_name: 'providers.missing_.legal_name',
  'document:identity': 'providers.missing_.document_identity',
  'document:business_registration': 'providers.missing_.document_business_registration',
} as const;

/** The checklist line for an item of `missing_for_submit` (unknown items read generically). */
function missingKey(item: string) {
  return MISSING_KEYS[item as keyof typeof MISSING_KEYS] ?? 'providers.workspace.incomplete';
}

const DOCUMENTS_FOR: Record<ProviderWorkspace['kind'], DocumentKind[]> = {
  guide: ['identity', 'tourism_registry', 'guide_license', 'insurance', 'other'],
  company: ['identity', 'business_registration', 'tourism_registry', 'insurance', 'other'],
};

function Workspace() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [terms, setTerms] = useState(false);
  const [uploading, setUploading] = useState<DocumentKind | null>(null);
  const [uploadFailed, setUploadFailed] = useState(false);
  const workspace = useQuery({
    queryKey: providerKeys.workspace(id),
    queryFn: () => getWorkspace(getApiClient(), id),
  });
  const data = workspace.data;
  const manager = data?.membership?.role === 'owner' || data?.membership?.role === 'manager';
  const documents = useQuery({
    queryKey: providerKeys.documents(id),
    queryFn: () => listDocuments(getApiClient(), id),
    enabled: manager,
  });
  const refresh = (updated?: ProviderWorkspace) => {
    if (updated) queryClient.setQueryData(providerKeys.workspace(id), updated);
    else void workspace.refetch();
    void documents.refetch();
    void queryClient.invalidateQueries({ queryKey: providerKeys.mine });
  };
  const submit = useMutation({
    mutationFn: () => submitProvider(getApiClient(), id, data?.terms_version ?? ''),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (documentId: string) => deleteDocument(getApiClient(), id, documentId),
    onSuccess: () => refresh(),
  });
  const close = useMutation({
    mutationFn: () => deactivateProvider(getApiClient(), id),
    onSuccess: refresh,
  });

  const upload = async (kind: DocumentKind, source: 'camera' | 'library') => {
    const picked = source === 'camera' ? await takePhoto() : await pickPhotos(1);
    if (picked === 'denied') return;
    const [photo] = picked;
    if (!photo) return;
    setUploading(kind);
    setUploadFailed(false);
    try {
      const mediaId = await uploadPhoto(getApiClient(), photo, 'provider_document');
      await addDocument(getApiClient(), id, { kind, media_id: mediaId });
      refresh();
    } catch {
      setUploadFailed(true);
    } finally {
      setUploading(null);
    }
  };
  const chooseSource = (kind: DocumentKind) =>
    showActions(t(`providers.document.${kind}`), t('providers.workspace.documentPrivacy'), [
      { text: t('providers.workspace.takePhoto'), onPress: () => void upload(kind, 'camera') },
      { text: t('providers.workspace.choosePhoto'), onPress: () => void upload(kind, 'library') },
      { text: t('common.cancel'), style: 'cancel' },
    ]);

  const missing = (data?.missing_for_submit ?? []).filter((m) => m !== 'terms');
  const canSubmit = data && (data.status === 'draft' || data.status === 'changes_requested');
  const submitProblem =
    submit.error instanceof ApiProblem && submit.error.code === 'provider_incomplete'
      ? t('providers.workspace.incomplete')
      : submit.error
        ? t('providers.workspace.submitFailed')
        : null;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen
        options={{ headerShown: true, title: data?.display_name ?? t('providers.workspace.title') }}
      />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {workspace.isError ? <Notice tone="error">{t('providers.missing')}</Notice> : null}
        {data ? (
          <>
            <View style={[styles.head, { gap: theme.spacing[3] }]}>
              <ProviderLogo provider={data} size={56} />
              <View style={[styles.fill, { gap: 2 }]}>
                <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
                  {data.display_name}
                </Text>
                <Text
                  style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
                  testID="workspace-status"
                >
                  {t(`providers.providerStatus.${data.status}`)}
                </Text>
              </View>
            </View>
            <Notice
              tone={
                data.status === 'approved'
                  ? 'success'
                  : data.status === 'rejected' || data.status === 'suspended'
                    ? 'error'
                    : 'info'
              }
              testID="workspace-status-notice"
            >
              {t(`providers.statusHelp.${data.status}`)}
            </Notice>
            {data.review_note &&
            (data.status === 'changes_requested' || data.status === 'rejected') ? (
              <Notice tone="info" testID="workspace-review-note">
                {t('providers.workspace.note', { note: data.review_note })}
              </Notice>
            ) : null}
            {data.status === 'suspended' && data.suspended_reason ? (
              <Notice tone="error">{data.suspended_reason}</Notice>
            ) : null}

            {manager && canSubmit ? (
              <View style={{ gap: theme.spacing[2] }} testID="workspace-checklist">
                <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
                  {t('providers.workspace.checklist')}
                </Text>
                {missing.length === 0 ? (
                  <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
                    {t('providers.workspace.ready')}
                  </Text>
                ) : (
                  missing.map((item) => (
                    <Text
                      key={item}
                      style={[theme.typography.body, { color: theme.colors.textPrimary }]}
                    >
                      {`• ${t(missingKey(item))}`}
                    </Text>
                  ))
                )}
              </View>
            ) : null}

            {manager ? (
              <View style={{ gap: theme.spacing[2] }}>
                <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
                  {t('providers.workspace.documents')}
                </Text>
                <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                  {t('providers.workspace.documentPrivacy')}
                </Text>
                {(documents.data?.data ?? []).map((doc) => (
                  <View
                    key={doc.id}
                    style={[styles.docRow, { borderColor: theme.colors.divider }]}
                    testID={`document-${doc.id}`}
                  >
                    <View style={styles.fill}>
                      <Text
                        style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}
                      >
                        {t(`providers.document.${doc.kind}`)}
                      </Text>
                      <Text
                        style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
                      >
                        {t(`providers.documentStatus.${doc.status}`)}
                      </Text>
                    </View>
                    {doc.status === 'pending' ? (
                      <Button
                        label={t('providers.workspace.removeDocument')}
                        variant="ghost"
                        onPress={() => remove.mutate(doc.id)}
                        testID={`document-remove-${doc.id}`}
                      />
                    ) : null}
                  </View>
                ))}
                {data.status === 'draft' ||
                data.status === 'changes_requested' ||
                data.status === 'approved'
                  ? DOCUMENTS_FOR[data.kind].map((kind) => (
                      <Button
                        key={kind}
                        label={t('providers.workspace.addDocument', {
                          document: t(`providers.document.${kind}`),
                        })}
                        variant="secondary"
                        icon="document-attach-outline"
                        onPress={() => chooseSource(kind)}
                        busy={uploading === kind}
                        disabled={uploading !== null}
                        testID={`document-add-${kind}`}
                      />
                    ))
                  : null}
                {uploadFailed ? (
                  <Notice tone="error">{t('providers.workspace.uploadFailed')}</Notice>
                ) : null}
              </View>
            ) : null}

            {manager && canSubmit ? (
              <View style={{ gap: theme.spacing[2] }}>
                <SwitchRow
                  label={t('providers.workspace.terms')}
                  value={terms}
                  onValueChange={setTerms}
                  testID="workspace-terms"
                />
                {submitProblem ? <Notice tone="error">{submitProblem}</Notice> : null}
                <Button
                  label={t('providers.workspace.submit')}
                  onPress={() => submit.mutate()}
                  disabled={!terms || missing.length > 0}
                  busy={submit.isPending}
                  testID="workspace-submit"
                />
              </View>
            ) : null}

            <MenuGroup title={t('providers.workspace.manage')}>
              {manager ? (
                <MenuRow
                  icon="create-outline"
                  label={t('providers.workspace.editProfile')}
                  onPress={() => router.push({ pathname: '/providers/apply', params: { id } })}
                  testID="workspace-edit"
                />
              ) : null}
              {manager ? (
                <MenuRow
                  icon="pricetags-outline"
                  label={t('providers.workspace.offerings')}
                  onPress={() =>
                    router.push({ pathname: '/providers/offerings/[id]', params: { id } })
                  }
                  testID="workspace-offerings"
                />
              ) : null}
              <MenuRow
                icon="mail-unread-outline"
                label={t('providers.workspace.inbox')}
                detail={data.inquiry_count > 0 ? String(data.inquiry_count) : undefined}
                onPress={() => router.push({ pathname: '/providers/inbox/[id]', params: { id } })}
                testID="workspace-inbox"
              />
              {data.kind === 'company' ? (
                <MenuRow
                  icon="people-outline"
                  label={t('providers.workspace.team')}
                  onPress={() => router.push({ pathname: '/providers/team/[id]', params: { id } })}
                  testID="workspace-team"
                />
              ) : null}
              {data.status === 'approved' ? (
                <MenuRow
                  icon="eye-outline"
                  label={t('providers.workspace.viewPublic')}
                  onPress={() => router.push({ pathname: '/providers/[id]', params: { id } })}
                  testID="workspace-public"
                />
              ) : null}
            </MenuGroup>
            {data.membership?.role === 'owner' &&
            data.status !== 'deactivated' &&
            data.status !== 'rejected' ? (
              <Button
                label={t('providers.workspace.close')}
                variant="ghost"
                onPress={() =>
                  Alert.alert(
                    t('providers.workspace.closeTitle'),
                    t('providers.workspace.closeBody'),
                    [
                      { text: t('common.cancel'), style: 'cancel' },
                      {
                        text: t('providers.workspace.close'),
                        style: 'destructive',
                        onPress: () => close.mutate(),
                      },
                    ],
                  )
                }
                testID="workspace-close"
              />
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  head: { flexDirection: 'row', alignItems: 'center' },
  docRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingVertical: 8,
    gap: 8,
  },
});
