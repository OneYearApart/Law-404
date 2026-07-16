import styles from './AuthField.module.css';

function AuthField({
  id,
  label,
  type = 'text',
  name,
  value,
  onChange,
  placeholder,
  autoComplete,
  Icon,
}) {
  return (
    <label className={styles.field} htmlFor={id}>
      <span className={styles.label}>{label}</span>
      <span className={styles.inputWrap}>
        {Icon && <Icon className={styles.icon} aria-hidden="true" />}
        <input
          className={styles.input}
          id={id}
          name={name}
          type={type}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          autoComplete={autoComplete}
          required
        />
      </span>
    </label>
  );
}

export default AuthField;
