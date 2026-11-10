import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Notice, TextField } from '@/components/Form';
import type { TripItem } from '@/features/explore/api';
import { type ItemFields, ITEM_KINDS, type ItemKind } from '@/features/trips/editor';
import { useAppTheme } from '@/theme/useAppTheme';

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

export interface ItemEditorProps {
  /** The item being edited; absent when adding one. */
  item?: TripItem;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
  onSave: (fields: ItemFields) => void;
  onDelete?: () => void;
  onMove?: (direction: 'up' | 'down') => void;
  onClose: () => void;
}

/** Add or change one itinerary item: what, when, notes; delete or move it within its day. */
export function ItemEditor({
  item,
  canMoveUp,
  canMoveDown,
  onSave,
  onDelete,
  onMove,
  onClose,
}: ItemEditorProps) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const [kind, setKind] = useState<ItemKind>(item?.kind ?? 'activity');
  const [title, setTitle] = useState(item?.title ?? '');
  const [time, setTime] = useState(item?.start_time?.slice(0, 5) ?? '');
  const [notes, setNotes] = useState(item?.notes ?? '');
  const timeValid = time.trim() === '' || HHMM.test(time.trim());
  const canSave = title.trim().length > 0 && timeValid;

  const save = () => {
    const fields: ItemFields = {
      kind,
      title: title.trim(),
      start_time: time.trim() || null,
      notes: notes.trim() || null,
    };
    if (item) {
      // Only what changed: a smaller edit is less likely to overwrite someone else's.
      const changed = Object.fromEntries(
        Object.entries(fields).filter(
          ([key, value]) => (item as unknown as Record<string, unknown>)[key] !== value,
        ),
      ) as ItemFields;
      if (Object.keys(changed).length) onSave(changed);
      onClose();
      return;
    }
    onSave(fields);
    onClose();
  };

  return (
    <Modal visible animationType="slide" onRequestClose={onClose} testID="item-editor">
      <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
        <ScrollView
          contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
          keyboardShouldPersistTaps="handled"
        >
          <Text
            accessibilityRole="header"
            style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
          >
            {item ? t('tripEditor.editItem') : t('tripEditor.newItem')}
          </Text>
          <View style={styles.chips} accessibilityRole="radiogroup">
            {ITEM_KINDS.map((value) => {
              const selected = value === kind;
              return (
                <Pressable
                  key={value}
                  onPress={() => setKind(value)}
                  accessibilityRole="radio"
                  accessibilityState={{ selected }}
                  style={[
                    styles.chip,
                    {
                      borderColor: selected ? theme.colors.primary : theme.colors.divider,
                      backgroundColor: selected ? theme.colors.primary : 'transparent',
                    },
                  ]}
                  testID={`item-kind-${value}`}
                >
                  <Text
                    style={[
                      theme.typography.label,
                      { color: selected ? theme.colors.onPrimary : theme.colors.textPrimary },
                    ]}
                  >
                    {t(`tripEditor.kinds.${value}`)}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <TextField
            label={t('tripEditor.title')}
            value={title}
            onChangeText={setTitle}
            maxLength={120}
            testID="item-title"
          />
          <TextField
            label={t('tripEditor.time')}
            value={time}
            onChangeText={setTime}
            placeholder="09:30"
            keyboardType="numbers-and-punctuation"
            maxLength={5}
            testID="item-time"
          />
          <TextField
            label={t('tripEditor.notes')}
            value={notes}
            onChangeText={setNotes}
            multiline
            maxLength={2000}
            testID="item-notes"
          />
          {!timeValid ? (
            <Notice tone="error" testID="item-time-error">
              {t('tripEditor.timeInvalid')}
            </Notice>
          ) : null}
          <Button
            label={t('tripEditor.save')}
            onPress={save}
            disabled={!canSave}
            testID="item-save"
          />
          {item && onMove ? (
            <View style={styles.row}>
              <View style={styles.fill}>
                <Button
                  label={t('tripEditor.moveUp')}
                  variant="secondary"
                  onPress={() => {
                    onMove('up');
                    onClose();
                  }}
                  disabled={!canMoveUp}
                  testID="item-move-up"
                />
              </View>
              <View style={styles.fill}>
                <Button
                  label={t('tripEditor.moveDown')}
                  variant="secondary"
                  onPress={() => {
                    onMove('down');
                    onClose();
                  }}
                  disabled={!canMoveDown}
                  testID="item-move-down"
                />
              </View>
            </View>
          ) : null}
          {item && onDelete ? (
            <Button
              label={t('tripEditor.delete')}
              variant="secondary"
              onPress={() => {
                onDelete();
                onClose();
              }}
              testID="item-delete"
            />
          ) : null}
          <Button
            label={t('common.cancel')}
            variant="secondary"
            onPress={onClose}
            testID="item-cancel"
          />
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', gap: 12 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
