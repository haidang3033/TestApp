plugins {
    id("com.android.application")
}

android {
    namespace = "com.randotone.notiflab"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.randotone.notiflab"
        minSdk = 26
        targetSdk = 36
        versionCode = 2
        versionName = "0.2.0"
    }

    signingConfigs {
        create("prototype") {
            storeFile = rootProject.file("notiflab-signing.keystore")
            storePassword = "notiflab-prototype"
            keyAlias = "notiflab-prototype"
            keyPassword = "notiflab-prototype"
        }
    }

    buildTypes {
        getByName("debug") {
            signingConfig = signingConfigs.getByName("prototype")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
